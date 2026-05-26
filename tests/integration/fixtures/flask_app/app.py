from flask import Flask, request
from auth import verify_user, issue_token
from db import find_user

app = Flask(__name__)


@app.route("/login", methods=["POST"])
def login():
    user = request.json["user"]
    pw = request.json["pw"]
    if verify_user(user, pw):
        return issue_token(user)
    return "unauthorized", 401


@app.route("/health")
def health():
    return "ok"
