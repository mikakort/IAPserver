from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route('/', methods=['POST'])
def receive_notification():
    data = request.get_json()
    if not data:
        print("⚠️ Received empty or invalid JSON")
        return jsonify({"status": "invalid"}), 400

    print("📩 Received App Store Server Notification:")
    print(data)

    # optionally, write to file or further process here

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    print("🚀 Flask server listening on http://localhost:80")
    app.run(host='0.0.0.0', port=80, debug=True)
