import sys
from pathlib import Path
from src.models.schemas import ActivitySchema, SportType, ParseResult
from datetime import date
from streamlit.testing.v1 import AppTest
from src.config import get_settings

def run():
    at = AppTest.from_file("src/ui/pages/1_Dashboard.py").run()
    at.text_input[0].set_value(get_settings().app_password).run()
    if at.exception:
        print(f"Exception: {at.exception[0]}")
    else:
        print("No exception, text_areas:", len(at.text_area))

run()
