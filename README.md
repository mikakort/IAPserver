# App Store Server Notification Server

An enhanced Flask server for handling Apple App Store Server Notifications with comprehensive functionality including database storage, user subscription tracking, receipt validation, webhooks, and monitoring.

## Features

- 🔔 **Notification Processing**: Handle all App Store notification types (purchases, renewals, cancellations, etc.)
- 🗄️ **Database Storage**: SQLite database for storing notifications and tracking user subscriptions
- 🎯 **User Subscription Tracking**: Real-time subscription status management
- 🔍 **Receipt Validation**: Validate receipts with Apple's servers
- 🪝 **Webhook Support**: Forward notifications to external services
- 📊 **Analytics & Monitoring**: Statistics dashboard and health checks
- 📝 **Comprehensive Logging**: Structured logging to files and console
- ⚙️ **Environment Configuration**: Flexible configuration via environment variables

## Quick Start

1. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment** (create `.env` file):

   ```bash
   SHARED_SECRET=your_app_store_shared_secret
   PORT=8080
   DEBUG=false
   ```

3. **Run the Server**:
   ```bash
   python server.py
   ```

## Configuration Options

Set these environment variables to configure the server:

| Variable                       | Default            | Description                                            |
| ------------------------------ | ------------------ | ------------------------------------------------------ |
| `SHARED_SECRET`                | `bomboclat`        | Your App-Specific Shared Secret from App Store Connect |
| `DATABASE_PATH`                | `notifications.db` | SQLite database file path                              |
| `LOG_LEVEL`                    | `INFO`             | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)  |
| `WEBHOOK_URL`                  | `None`             | URL to forward notifications to external services      |
| `APPLE_RECEIPT_VALIDATION_URL` | Production URL     | Apple's receipt validation endpoint                    |
| `PORT`                         | `8080`             | Server port                                            |
| `DEBUG`                        | `false`            | Enable Flask debug mode                                |

## API Endpoints

### Core Endpoints

#### `POST /`

Main endpoint for receiving App Store Server Notifications.

**Request**: App Store notification payload
**Response**: `{"status": "ok"}` or error status

#### `POST /validate-receipt`

Manually validate an App Store receipt.

**Request**:

```json
{
  "receipt_data": "base64_encoded_receipt_data"
}
```

**Response**: Apple's receipt validation response

#### `GET /user/<user_id>/subscription`

Get a user's current subscription status.

**Response**:

```json
{
  "user_id": "user123",
  "product_id": "premium_subscription",
  "subscription_status": "active",
  "expires_date": "1640995200000",
  "auto_renew_status": 1
}
```

### Monitoring Endpoints

#### `GET /health`

Health check endpoint for monitoring.

**Response**:

```json
{
  "status": "healthy",
  "timestamp": "2023-12-01T12:00:00Z",
  "database": "connected"
}
```

#### `GET /stats`

Get notification and subscription statistics.

**Response**:

```json
{
  "total_notifications": 150,
  "active_subscriptions": 45,
  "notification_counts": {
    "INITIAL_BUY": 50,
    "RENEWAL": 75,
    "CANCEL": 25
  }
}
```

## Supported Notification Types

The server handles all App Store Server Notification types:

- `INITIAL_BUY` - Initial purchase
- `CANCEL` - Subscription cancelled
- `RENEWAL` - Subscription renewed
- `INTERACTIVE_RENEWAL` - User renewed through App Store
- `DID_CHANGE_RENEWAL_PREF` - User changed renewal preferences
- `DID_CHANGE_RENEWAL_STATUS` - Renewal status changed
- `DID_FAIL_TO_RENEW` - Renewal failed
- `DID_RECOVER` - Billing issue resolved
- `REFUND` - Purchase refunded
- `REVOKE` - Family sharing member lost access
- `PRICE_INCREASE_CONSENT` - User consented to price increase
- `CONSUMPTION_REQUEST` - Consumable product used

## Database Schema

The server creates three main tables:

### `notifications`

Stores all received notifications with full payload data.

### `user_subscriptions`

Tracks current subscription status for each user.

### `webhook_logs`

Logs webhook delivery attempts and responses.

## Webhook Integration

If `WEBHOOK_URL` is configured, the server will forward processed notifications to your external service:

**Webhook Payload**:

```json
{
  "notification_id": 123,
  "notification_type": "RENEWAL",
  "user_id": "user123",
  "product_id": "premium_subscription",
  "transaction_id": "1000000123456789",
  "timestamp": "2023-12-01T12:00:00Z"
}
```

## Logging

The server provides comprehensive logging:

- **Console Output**: Real-time status and errors
- **File Logging**: Persistent logs in `app_store_notifications.log`
- **Structured Format**: Timestamp, level, and detailed messages

## Security Features

- **Shared Secret Validation**: Validates Apple's shared secret
- **Error Handling**: Comprehensive error responses
- **Input Validation**: Validates all incoming data
- **Rate Limiting Ready**: Designed for production rate limiting

## Production Deployment

For production deployment:

1. **Set up HTTPS**: Use a reverse proxy like Nginx
2. **Configure Database**: Consider PostgreSQL for high volume
3. **Set up Monitoring**: Use the `/health` endpoint
4. **Configure Logging**: Set up log rotation
5. **Environment Variables**: Use production secrets management

## Example Usage

1. **Set up App Store Connect**: Configure your shared secret in App Store Connect
2. **Deploy Server**: Deploy to your production environment
3. **Configure Webhook URL**: Point App Store Connect to your server
4. **Monitor**: Use `/health` and `/stats` endpoints for monitoring

## Troubleshooting

- **Shared Secret Mismatch**: Check `SHARED_SECRET` environment variable
- **Database Issues**: Check file permissions for SQLite database
- **Webhook Failures**: Check `webhook_logs` table for delivery status
- **Receipt Validation**: Ensure correct Apple URL (sandbox vs production)

## License

This project is open source and available under the MIT License.
