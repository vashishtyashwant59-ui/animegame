from flask import Flask
from threading import Thread
import os

app = Flask('')


@app.route('/')
def home():
    return "I am alive"


def run():
    # Use PORT env var if provided (platforms like Render expose it)
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()