from flask import Flask, request, jsonify
import os
import json
import sqlite3
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import base64
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import time

app = Flask(__name__)

# Configuration


class Config:
    SHARED_SECRET = os.getenv("SHARED_SECRET", "bomboclat")
    DATABASE_PATH = os.getenv("DATABASE_PATH", "notifications.db")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", None)
    APPLE_RECEIPT_VALIDATION_URL = os.getenv(
        "APPLE_RECEIPT_VALIDATION_URL",
        "https://buy.itunes.apple.com/verifyReceipt"  # Production
        # "https://sandbox.itunes.apple.com/verifyReceipt"  # Sandbox
    )
    PORT = int(os.getenv("PORT", 8080))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"


# Logging setup
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_store_notifications.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Notification types from App Store Server Notifications
NOTIFICATION_TYPES = {
    'INITIAL_BUY': 'Initial purchase',
    'CANCEL': 'Subscription cancelled',
    'RENEWAL': 'Subscription renewed',
    'INTERACTIVE_RENEWAL': 'User renewed through App Store',
    'DID_CHANGE_RENEWAL_PREF': 'User changed renewal preferences',
    'DID_CHANGE_RENEWAL_STATUS': 'Renewal status changed',
    'DID_FAIL_TO_RENEW': 'Renewal failed',
    'DID_RECOVER': 'Billing issue resolved',
    'REFUND': 'Purchase refunded',
    'REVOKE': 'Family sharing member lost access',
    'PRICE_INCREASE_CONSENT': 'User consented to price increase',
    'CONSUMPTION_REQUEST': 'Consumable product used'
}


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_type TEXT,
                    transaction_id TEXT,
                    original_transaction_id TEXT,
                    bundle_id TEXT,
                    product_id TEXT,
                    user_id TEXT,
                    expires_date TEXT,
                    purchase_date TEXT,
                    cancellation_date TEXT,
                    raw_payload TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'processed'
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE,
                    product_id TEXT,
                    transaction_id TEXT,
                    original_transaction_id TEXT,
                    subscription_status TEXT,
                    expires_date TEXT,
                    auto_renew_status INTEGER,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id INTEGER,
                    webhook_url TEXT,
                    response_status INTEGER,
                    response_body TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (notification_id) REFERENCES notifications (id)
                )
            """)

    def store_notification(self, notification_data: Dict[str, Any]) -> int:
        """Store notification in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO notifications (
                    notification_type, transaction_id, original_transaction_id,
                    bundle_id, product_id, user_id, expires_date, purchase_date,
                    cancellation_date, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                notification_data.get('notification_type'),
                notification_data.get('transaction_id'),
                notification_data.get('original_transaction_id'),
                notification_data.get('bundle_id'),
                notification_data.get('product_id'),
                notification_data.get('user_id'),
                notification_data.get('expires_date'),
                notification_data.get('purchase_date'),
                notification_data.get('cancellation_date'),
                json.dumps(notification_data.get('raw_payload', {}))
            ))
            return cursor.lastrowid

    def update_user_subscription(self, user_data: Dict[str, Any]):
        """Update user subscription status"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_subscriptions (
                    user_id, product_id, transaction_id, original_transaction_id,
                    subscription_status, expires_date, auto_renew_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_data.get('user_id'),
                user_data.get('product_id'),
                user_data.get('transaction_id'),
                user_data.get('original_transaction_id'),
                user_data.get('subscription_status'),
                user_data.get('expires_date'),
                user_data.get('auto_renew_status', 1)
            ))

    def get_user_subscription(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's current subscription status"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM user_subscriptions WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


class NotificationProcessor:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def parse_notification(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse App Store notification data"""
        try:
            # Handle both v1 and v2 notification formats
            notification_type = raw_data.get('notification_type')

            # Extract receipt data
            latest_receipt_info = raw_data.get('latest_receipt_info', [{}])
            if latest_receipt_info:
                receipt_info = latest_receipt_info[0] if isinstance(
                    latest_receipt_info, list) else latest_receipt_info
            else:
                receipt_info = {}

            # Extract unified receipt info
            unified_receipt = raw_data.get('unified_receipt', {})
            latest_info = unified_receipt.get('latest_receipt_info', [{}])
            if latest_info:
                receipt_info.update(latest_info[0] if isinstance(
                    latest_info, list) else latest_info)

            return {
                'notification_type': notification_type,
                'transaction_id': receipt_info.get('transaction_id'),
                'original_transaction_id': receipt_info.get('original_transaction_id'),
                'bundle_id': raw_data.get('bundle_id') or receipt_info.get('bundle_id'),
                'product_id': receipt_info.get('product_id'),
                'user_id': receipt_info.get('web_order_line_item_id') or receipt_info.get('app_account_token'),
                'expires_date': receipt_info.get('expires_date_ms'),
                'purchase_date': receipt_info.get('purchase_date_ms'),
                'cancellation_date': receipt_info.get('cancellation_date_ms'),
                'auto_renew_status': raw_data.get('auto_renew_status'),
                'raw_payload': raw_data
            }
        except Exception as e:
            logger.error(f"Error parsing notification: {e}")
            return {'raw_payload': raw_data}

    def process_notification(self, notification_data: Dict[str, Any]) -> bool:
        """Process the notification based on its type"""
        notification_type = notification_data.get('notification_type')

        try:
            # Store notification
            notification_id = self.db_manager.store_notification(
                notification_data)
            logger.info(
                f"Stored notification {notification_id} of type {notification_type}")

            # Update user subscription status
            if notification_data.get('user_id'):
                subscription_status = self._determine_subscription_status(
                    notification_type)
                user_data = {
                    'user_id': notification_data.get('user_id'),
                    'product_id': notification_data.get('product_id'),
                    'transaction_id': notification_data.get('transaction_id'),
                    'original_transaction_id': notification_data.get('original_transaction_id'),
                    'subscription_status': subscription_status,
                    'expires_date': notification_data.get('expires_date'),
                    'auto_renew_status': notification_data.get('auto_renew_status', 1)
                }
                self.db_manager.update_user_subscription(user_data)
                logger.info(
                    f"Updated subscription for user {notification_data.get('user_id')}")

            # Send webhook if configured
            if Config.WEBHOOK_URL:
                self._send_webhook(notification_id, notification_data)

            return True

        except Exception as e:
            logger.error(f"Error processing notification: {e}")
            return False

    def _determine_subscription_status(self, notification_type: str) -> str:
        """Determine subscription status based on notification type"""
        status_map = {
            'INITIAL_BUY': 'active',
            'RENEWAL': 'active',
            'INTERACTIVE_RENEWAL': 'active',
            'CANCEL': 'cancelled',
            'DID_FAIL_TO_RENEW': 'expired',
            'DID_RECOVER': 'active',
            'REFUND': 'refunded',
            'REVOKE': 'revoked'
        }
        return status_map.get(notification_type, 'unknown')

    def _send_webhook(self, notification_id: int, notification_data: Dict[str, Any]):
        """Send webhook notification to external service"""
        try:
            payload = {
                'notification_id': notification_id,
                'notification_type': notification_data.get('notification_type'),
                'user_id': notification_data.get('user_id'),
                'product_id': notification_data.get('product_id'),
                'transaction_id': notification_data.get('transaction_id'),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            response = requests.post(
                Config.WEBHOOK_URL,
                json=payload,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )

            # Log webhook response
            with sqlite3.connect(Config.DATABASE_PATH) as conn:
                conn.execute("""
                    INSERT INTO webhook_logs (notification_id, webhook_url, response_status, response_body)
                    VALUES (?, ?, ?, ?)
                """, (notification_id, Config.WEBHOOK_URL, response.status_code, response.text[:1000]))

            logger.info(
                f"Webhook sent for notification {notification_id}, status: {response.status_code}")

        except Exception as e:
            logger.error(
                f"Failed to send webhook for notification {notification_id}: {e}")


class ReceiptValidator:
    @staticmethod
    def validate_receipt(receipt_data: str) -> Dict[str, Any]:
        """Validate receipt with Apple's servers"""
        try:
            payload = {
                'receipt-data': receipt_data,
                'password': Config.SHARED_SECRET,
                'exclude-old-transactions': True
            }

            response = requests.post(
                Config.APPLE_RECEIPT_VALIDATION_URL,
                json=payload,
                timeout=30
            )

            return response.json()

        except Exception as e:
            logger.error(f"Receipt validation failed: {e}")
            return {'status': -1, 'error': str(e)}


# Initialize components
db_manager = DatabaseManager(Config.DATABASE_PATH)
notification_processor = NotificationProcessor(db_manager)


@app.route('/', methods=['POST'])
def receive_notification():
    """Main endpoint for receiving App Store Server Notifications"""
    try:
        data = request.get_json()
        if not data:
            logger.warning("Received empty or invalid JSON")
            return jsonify({"status": "invalid"}), 400

        logger.info("📩 Received App Store Server Notification")

        # Validate shared secret
        received_secret = data.get("password")
        if received_secret:
            if received_secret == Config.SHARED_SECRET:
                logger.info("✅ Shared Secret matches")
            else:
                logger.warning("❌ Shared Secret does NOT match!")
                return jsonify({"status": "invalid_shared_secret"}), 403
        else:
            logger.info("ℹ️ No shared secret found in payload")

        # Parse and process notification
        notification_data = notification_processor.parse_notification(data)
        notification_type = notification_data.get('notification_type')

        if notification_type in NOTIFICATION_TYPES:
            logger.info(
                f"Processing {notification_type}: {NOTIFICATION_TYPES[notification_type]}")
        else:
            logger.warning(f"Unknown notification type: {notification_type}")

        # Process the notification
        success = notification_processor.process_notification(
            notification_data)

        if success:
            return jsonify({"status": "ok"}), 200
        else:
            return jsonify({"status": "processing_error"}), 500

    except Exception as e:
        logger.error(f"Error handling notification: {e}")
        return jsonify({"status": "server_error", "error": str(e)}), 500


@app.route('/validate-receipt', methods=['POST'])
def validate_receipt():
    """Endpoint for manual receipt validation"""
    try:
        data = request.get_json()
        receipt_data = data.get('receipt_data')

        if not receipt_data:
            return jsonify({"status": "invalid", "error": "receipt_data required"}), 400

        result = ReceiptValidator.validate_receipt(receipt_data)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Receipt validation error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/user/<user_id>/subscription', methods=['GET'])
def get_user_subscription(user_id: str):
    """Get user's current subscription status"""
    try:
        subscription = db_manager.get_user_subscription(user_id)
        if subscription:
            return jsonify(subscription), 200
        else:
            return jsonify({"status": "not_found"}), 404

    except Exception as e:
        logger.error(f"Error fetching user subscription: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        with sqlite3.connect(Config.DATABASE_PATH) as conn:
            conn.execute("SELECT 1")

        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected"
        }), 200

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get notification statistics"""
    try:
        with sqlite3.connect(Config.DATABASE_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Get notification counts by type
            cursor = conn.execute("""
                SELECT notification_type, COUNT(*) as count 
                FROM notifications 
                GROUP BY notification_type
            """)
            notification_counts = {
                row['notification_type']: row['count'] for row in cursor.fetchall()}

            # Get total notifications
            cursor = conn.execute(
                "SELECT COUNT(*) as total FROM notifications")
            total_notifications = cursor.fetchone()['total']

            # Get active subscriptions
            cursor = conn.execute("""
                SELECT COUNT(*) as active 
                FROM user_subscriptions 
                WHERE subscription_status = 'active'
            """)
            active_subscriptions = cursor.fetchone()['active']

            return jsonify({
                "total_notifications": total_notifications,
                "active_subscriptions": active_subscriptions,
                "notification_counts": notification_counts
            }), 200

    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    logger.info(
        f"🚀 App Store Notification Server starting on port {Config.PORT}")
    logger.info(f"📊 Database: {Config.DATABASE_PATH}")
    logger.info(f"🔗 Webhook URL: {Config.WEBHOOK_URL or 'Not configured'}")

    app.run(host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
