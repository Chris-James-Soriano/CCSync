import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    HOURS = [
        "7 AM",
        "8 AM",
        "9 AM",
        "10 AM",
        "11 AM",
        "12 PM",
        "1 PM",
        "2 PM",
        "3 PM",
        "4 PM",
        "5 PM",
    ]
