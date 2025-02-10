from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello, Gunicorn1!"

if __name__ == "__main__":
    app.run()  # Not needed for Gunicorn
