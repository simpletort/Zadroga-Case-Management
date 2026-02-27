from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**`requirements.txt`**
```
flask==3.0.3
gunicorn==22.0.0