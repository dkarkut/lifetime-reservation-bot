import os
import random
import time
import re
import datetime
import smtplib
import requests
import warnings
import pytz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Clear cached env vars
for key in list(os.environ.keys()):
    del os.environ[key]

load_dotenv(override=True)

# ==============================
# TIME CONFIG
# ==============================
CST = pytz.timezone("America/Chicago")
BOOKING_START_TIME = datetime.time(10, 1)    
BOOKING_CUTOFF_TIME = datetime.time(20, 15)  
RETRY_INTERVAL_SECONDS = 60

def send_early_startup_notification():
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        who = os.getenv("WHO_AM_I", "Unknown")
        if not token or not chat_id: return
        now_cst = datetime.datetime.now(CST).strftime("%Y-%m-%d %I:%M:%S %p CST")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🚀 <b>Lifetime Bot Triggered — {who}</b>\nTime: {now_cst}",
            "parse_mode": "HTML"
        }
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Startup notification failed: {e}")

class LifetimeReservationBot:
    def __init__(self):
        self.setup_config()
        self.setup_webdriver()

    def setup_config(self):
        self.USERNAME = os.getenv("LIFETIME_USERNAME")
        self.PASSWORD = os.getenv("LIFETIME_PASSWORD")
        self.TARGET_CLASS = os.getenv("TARGET_CLASS")
        self.TARGET_INSTRUCTOR = os.getenv("TARGET_INSTRUCTOR")
        self.TARGET_DATE = os.getenv("TARGET_DATE")
        self.START_TIME = os.getenv("START_TIME")
        self.END_TIME = os.getenv("END_TIME")
        self.LIFETIME_CLUB_NAME = os.getenv("LIFETIME_CLUB_NAME")
        self.LIFETIME_CLUB_STATE = os.getenv("LIFETIME_CLUB_STATE")
        self.NOTIFICATION_METHOD = os.getenv("NOTIFICATION_METHOD", "email").lower()
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
        self.WHO_AM_I = os.getenv("WHO_AM_I")

    def is_valid_booking_day(self):
        return datetime.datetime.now(CST).weekday() in [6, 0, 2, 3]

    def send_telegram(self, message):
        try:
            url = f"https://api.telegram.org/bot{self.TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": self.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            requests.post(url, data=payload, timeout=10)
        except: pass

    def send_notification(self, subject, message):
        if self.NOTIFICATION_METHOD == "telegram":
            self.send_telegram(f"<b>{subject}</b>\n{message}")
        print(f"📡 Notification: {subject}")

    def setup_webdriver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)

    def login(self):
        self.driver.get("https://my.lifetime.life/login.html")
        self.wait.until(EC.presence_of_element_located((By.NAME, "username"))).send_keys(self.USERNAME)
        self.wait.until(EC.presence_of_element_located((By.NAME, "password"))).send_keys(self.PASSWORD + Keys.RETURN)
        time.sleep(4)
        print("✅ Logged in")

    def get_target_date(self):
        if self.TARGET_DATE: return self.TARGET_DATE
        return (datetime.datetime.now(CST) + datetime.timedelta(days=8)).strftime("%Y-%m-%d")

    def navigate_to_schedule(self, target_date):
        club_name = self.LIFETIME_CLUB_NAME.replace(" ", "+")
        club_seg = self.LIFETIME_CLUB_NAME.replace(" ", "-").lower()
        url = f"https://my.lifetime.life/clubs/{self.LIFETIME_CLUB_STATE.lower()}/{club_seg}/classes.html?selectedDate={target_date}&location={club_name}"
        self.driver.get(url)
        time.sleep(3)
        return True

    def find_target_class(self):
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        classes = self.driver.find_elements(By.CLASS_NAME, "planner-entry")
        for c in classes:
            txt = c.text.lower()
            if self.TARGET_CLASS.lower() in txt and self.START_TIME.lower() in txt:
                print(f"✅ Match Found: {c.text[:50]}...")
                return c.find_element(By.TAG_NAME, "a")
        return None

    def _click_reserve_button_v3(self) -> str:
        """New logic: Checks IDs first, then scans text for ONLY specific buttons."""
        time.sleep(4)
        
        # 1. Check for specific Life Time ID
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[data-test-id='reserveButton']")
        
        # 2. If ID not found, look for buttons specifically in the MAIN section of the page
        if not buttons:
            buttons = self.driver.find_elements(By.XPATH, "//main//button")

        print(f"🔍 Analyzing {len(buttons)} buttons on page...")
        
        for btn in buttons:
            txt = (btn.text or "").strip()
            if not txt: continue
            
            # Print for logs so you can see why it's failing
            print(f"   - Button found: '{txt}'")

            # Check for "Already Reserved" state
            if any(x in txt for x in ["Cancel", "Leave Waitlist", "Unreserve"]):
                return "ALREADY_DONE"

            # Check for "Available" state
            if any(x in txt for x in ["Reserve", "Add to Waitlist", "Waitlist"]):
                self.driver.execute_script("arguments[0].scrollIntoView();", btn)
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", btn)
                return "CLICKED"
        
        # If we see "Registration Opens" text, it's not ready yet
        page_text = self.driver.page_source
        if "Registration opens" in page_text or "Booking opens" in page_text:
            print("⏳ Booking window not yet open on website.")
            return "NOT_OPEN"

        return "NOT_FOUND"

    def reserve_class(self) -> str:
        if not self.is_valid_booking_day(): return "EXIT"
        target_date = self.get_target_date()
        
        try:
            self.login()
            if not self.navigate_to_schedule(target_date): return "RETRY"
            
            link = self.find_target_class()
            if not link: 
                print("❌ Class not found on schedule yet.")
                return "RETRY"

            self.driver.get(link.get_attribute("href"))
            
            status = self._click_reserve_button_v3()

            if status == "ALREADY_DONE":
                return "SUCCESS_SILENT"

            if status == "CLICKED":
                if "pickleball" in (self.TARGET_CLASS or "").lower():
                    # Waiver check
                    try: self.driver.find_element(By.ID, "acceptwaiver").click()
                    except: pass
                
                # Click Finish
                try:
                    finish = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Finish')]")))
                    finish.click()
                    print("🏁 Finish button clicked.")
                except: pass

                # Verify
                time.sleep(3)
                if "reservation is complete" in self.driver.page_source.lower() or "success" in self.driver.page_source.lower():
                    self.send_notification("Lifetime Bot - Success", f"✅ Reserved: {self.TARGET_CLASS}\nDate: {target_date}")
                    return "SUCCESS_NEW"
                else:
                    print("⚠️ Clicked reserve but confirmation page didn't appear.")
                    return "RETRY"

            return "RETRY"
        except Exception as e:
            print(f"❌ Error: {e}")
            return "RETRY"
        finally:
            self.driver.quit()

def cleanup_chrome():
    try: os.system("pkill -f chrome || true")
    except: pass

def main():
    who = os.getenv("WHO_AM_I", "Unknown")
    print(f"🚀 Starting for {who}")
    
    # Stagger starts
    time.sleep(random.randint(1, 15))
    
    # Wait until 10:01
    now = datetime.datetime.now(CST)
    start = now.replace(hour=10, minute=1, second=0, microsecond=0)
    if now < start:
        print(f"⏳ Waiting until 10:01 AM CST...")
        time.sleep((start - now).total_seconds())

    while True:
        now = datetime.datetime.now(CST)
        if now.hour == 10 and now.minute >= 15:
            bot = LifetimeReservationBot()
            bot.send_notification("Lifetime Bot - Failed", f"❌ {who}: Failed by 10:15 AM.")
            return

        cleanup_chrome()
        bot = LifetimeReservationBot()
        result = bot.reserve_class()
        
        if result in ["SUCCESS_NEW", "SUCCESS_SILENT"]:
            print(f"✅ {who}: Finished successfully.")
            return
        
        print(f"🔁 Retrying in {RETRY_INTERVAL_SECONDS}s...")
        time.sleep(RETRY_INTERVAL_SECONDS)

if __name__ == "__main__":
    send_early_startup_notification()
    main()
