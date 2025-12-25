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

# ======================================================
# EARLY STARTUP NOTIFICATION
# Sends Telegram message as soon as script is triggered
# (before waiting, Selenium, or main loop)
# ======================================================

def send_early_startup_notification():
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        who = os.getenv("WHO_AM_I", "Unknown")

        if not token or not chat_id:
            print("⚠️ Telegram startup notification skipped (missing token/chat id)")
            return

        now_cst = datetime.datetime.now(CST).strftime("%Y-%m-%d %I:%M:%S %p CST")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": (
                f"🚀 <b>Lifetime Bot Triggered — {who}</b>\n"
                f"Time: {now_cst}\n"
                "Status: Script loaded and execution has begun."
            ),
            "parse_mode": "HTML"
        }

        requests.post(url, data=payload, timeout=10)

    except Exception as e:
        print(f"⚠️ Early startup notification failed: {e}")

# ==============================
# TIME CONFIG
# ==============================

CST = pytz.timezone("America/Chicago")

BOOKING_START_TIME = datetime.time(10, 1)    # 10:01 AM CST = 10, 1
BOOKING_CUTOFF_TIME = datetime.time(20, 15)  # FIXED: Changed from 20 (8PM) to 10 (10AM)
RETRY_INTERVAL_SECONDS = 60
SUCCESS_FLAG_FILE = ".booking_success"


class LifetimeReservationBot:
    def __init__(self):
        self.setup_config()
        self.setup_email_config()
        self.setup_sms_config()
        self.setup_webdriver()

    def setup_config(self):
        self.RUN_ON_SCHEDULE = os.getenv("RUN_ON_SCHEDULE", "false").lower() == "true"
        self.LOGIN_URL = "https://my.lifetime.life/login.html"
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
        self.SMS_CARRIER = os.getenv("SMS_CARRIER", "").lower()
        self.SMS_NUMBER = os.getenv("SMS_NUMBER", "")
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
        self.WHO_AM_I = os.getenv("WHO_AM_I")

        if not self.LIFETIME_CLUB_NAME or not self.LIFETIME_CLUB_STATE:
            raise ValueError("LIFETIME_CLUB_NAME and LIFETIME_CLUB_STATE are required")

        if not self.USERNAME or not self.PASSWORD:
            raise ValueError("LIFETIME_USERNAME and LIFETIME_PASSWORD are required")

    # ======================================================
    # VALID BOOKING DAYS (BOOKING DAYS, NOT CLASS DAYS)
    # Run on: Sunday, Monday, Wednesday, Thursday
    # (books Mon/Tue/Thu/Fri classes +8 days)
    # ======================================================

    def is_valid_booking_day(self):
        # Python: Monday=0 ... Sunday=6
        return datetime.datetime.now(CST).weekday() in [6, 0, 2, 3]

    # ==============================
    # NOTIFICATIONS
    # ==============================

    def send_telegram(self, message):
        try:
            if not self.TELEGRAM_TOKEN or not self.TELEGRAM_CHAT_ID:
                print("⚠️ Telegram config missing")
                return
            url = f"https://api.telegram.org/bot{self.TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": self.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            r = requests.post(url, data=payload, timeout=10)
            if r.status_code != 200:
                print(f"❌ Telegram failed: {r.text}")
        except Exception as e:
            print(f"❌ Telegram exception: {e}")

    def setup_email_config(self):
        self.EMAIL_SENDER = os.getenv("EMAIL_SENDER")
        self.EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
        self.EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
        self.SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

    def setup_sms_config(self):
        self.SMS_GATEWAYS = {
            "att": "mms.att.net",
            "tmobile": "tmomail.net",
            "verizon": "vtext.com",
        }

    def send_notification(self, subject, message):
        if self.NOTIFICATION_METHOD == "telegram":
            self.send_telegram(f"<b>{subject}</b>\n{message}")
            print(f"📡 Telegram: {subject}")
        else:
            self.send_email(subject, message)
            print(f"📧 Email: {subject}")

    def send_email(self, subject, message):
        if not (self.EMAIL_SENDER and self.EMAIL_PASSWORD and self.EMAIL_RECEIVER):
            print("⚠️ Email config missing; cannot send email notification")
            return

        try:
            msg = MIMEMultipart()
            msg["From"] = self.EMAIL_SENDER
            msg["To"] = self.EMAIL_RECEIVER
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain"))

            with smtplib.SMTP(self.SMTP_SERVER, self.SMTP_PORT) as server:
                server.starttls()
                server.login(self.EMAIL_SENDER, self.EMAIL_PASSWORD)
                server.send_message(msg)
        except Exception as e:
            print(f"❌ Failed to send email: {e}")

    # ==============================
    # SELENIUM (CI-SAFE)
    # ==============================

    def setup_webdriver(self):
        options = webdriver.ChromeOptions()

        # REQUIRED for GitHub Actions / Linux runners
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        # Reduce crash risk
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-software-rasterizer")

        # IMPORTANT: Use Chrome/ChromeDriver provided by the runner (setup-chrome)
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 30)

    # ==============================
    # BUSINESS LOGIC
    # ==============================

    def get_target_date(self):
        """Use TARGET_DATE from env (GitHub writes +8 days). Fallback to +8 local if missing."""
        if self.TARGET_DATE:
            return self.TARGET_DATE
        return (datetime.datetime.now(CST) + datetime.timedelta(days=8)).strftime("%Y-%m-%d")

    def login(self):
        self.driver.get(self.LOGIN_URL)
        self.wait.until(EC.presence_of_element_located((By.NAME, "username"))).send_keys(self.USERNAME)
        self.wait.until(EC.presence_of_element_located((By.NAME, "password"))).send_keys(self.PASSWORD + Keys.RETURN)
        time.sleep(3)
        print("✅ Logged in")

    def _format_club_url_segment(self, club_name: str) -> str:
        name = club_name.replace("Life Time", "").replace("LifeTime", "").strip()
        name = name.strip(" -")
        name = name.replace(" at ", "-").replace(" - ", "-")
        name = name.lower().replace(" ", "-")
        name = "".join(c for c in name if c.isalnum() or c == "-")
        return name

    def navigate_to_schedule(self, target_date: str) -> bool:
        club_state = (self.LIFETIME_CLUB_STATE or "").lower()
        club_name = self.LIFETIME_CLUB_NAME or ""
        if not club_state or not club_name:
            raise Exception("Club state/name missing")

        url_segment = self._format_club_url_segment(club_name)
        url_param = club_name.replace(" ", "+")
        schedule_url = (
            f"https://my.lifetime.life/clubs/{club_state}/{url_segment}/classes.html?"
            f"teamMemberView=true&selectedDate={target_date}&mode=day&location={url_param}"
        )

        self.driver.get(schedule_url)
        print(f"🔄 Opened schedule: {target_date}")

        try:
            self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "planner-entry")))
            return True
        except Exception:
            return False

    def _is_matching_class(self, element) -> bool:
        class_text = element.text.replace("\n", " ").strip()
        time_match = re.search(
            r"(\d{1,2}:\d{2})\s?to\s?(\d{1,2}:\d{2})\s?(AM|PM)",
            class_text,
            re.IGNORECASE
        )
        if not time_match:
            return False

        start_time = f"{time_match.group(1)} {time_match.group(3)}"
        end_time = f"{time_match.group(2)} {time_match.group(3)}"

        return (
            self.TARGET_CLASS.lower().strip() in class_text.lower().strip()
            and start_time.strip() == self.START_TIME.strip()
            and end_time.strip() == self.END_TIME.strip()
            and self.TARGET_INSTRUCTOR.lower().strip() in class_text.lower().strip()
        )

    def find_target_class(self):
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        class_elements = self.wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class, 'planner-entry')]"))
        )

        print(f"🔍 Found {len(class_elements)} classes")
        for element in class_elements:
            if self._is_matching_class(element):
                class_text = element.text.replace("\n", " ").strip()
                print(f"✅ Match: {class_text[:80]}...")
                return element.find_element(By.TAG_NAME, "a")

        return None

    def _click_reserve_button(self) -> bool:
        time.sleep(2)
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[data-test-id='reserveButton']")
        if not buttons:
            buttons = self.driver.find_elements(
                By.XPATH,
                "//button[contains(text(), 'Reserve')] | "
                "//button[contains(text(), 'Add to Waitlist')] | "
                "//button[contains(text(), 'Cancel')] | "
                "//button[contains(text(), 'Leave Waitlist')]"
            )

        if not buttons:
            raise Exception("No reserve/waitlist/cancel button found")

        for button in buttons:
            txt = button.text or ""
            if "Cancel" in txt or "Leave Waitlist" in txt:
                print("✅ Already reserved / waitlisted")
                self.already_reserved = True
                return False

            if "Reserve" in txt or "Add to Waitlist" in txt:
                self.driver.execute_script("arguments[0].scrollIntoView();", button)
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", button)
                return True

        raise Exception("Could not click reserve/waitlist button")

    def _handle_waiver(self):
        checkbox_label = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//label[@for='acceptwaiver']")))
        checkbox_label.click()
        time.sleep(1)

        checkbox = self.driver.find_element(By.ID, "acceptwaiver")
        if not checkbox.is_selected():
            checkbox_label.click()
            time.sleep(1)

    def _click_finish(self):
        finish_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Finish')]")))
        finish_button.click()

    def _verify_confirmation(self) -> bool:
        try:
            self.wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h1[contains(text(), 'Your reservation is complete')]")
                )
            )
            return True
        except Exception:
            return False

    def _complete_reservation(self) -> bool:
        try:
            if not self._click_reserve_button():
                return True  # already reserved is success

            if "pickleball" in (self.TARGET_CLASS or "").lower():
                self._handle_waiver()

            self._click_finish()
            return self._verify_confirmation()
        except Exception as e:
            print(f"❌ Complete reservation error: {e}")
            return False

    def reserve_class(self) -> str:
        if not self.is_valid_booking_day():
            print("❌ Not a valid booking day. Exiting.")
            return "EXIT"

        target_date = self.get_target_date()
        class_details = f"Class: {self.TARGET_CLASS} | {self.START_TIME} | {self.WHO_AM_I}"

        try:
            self.login()
            if not self.navigate_to_schedule(target_date):
                raise Exception("Failed to load schedule")

            class_link = self.find_target_class()
            if not class_link:
                # If class isn't found, it might be too early. Return RETRY to loop.
                print(f"🔍 Class not found for {self.WHO_AM_I}. Might be too early.")
                return "RETRY"

            # Go to class page
            self.driver.get(class_link.get_attribute("href"))
            
            # --- CHECK CURRENT STATUS ---
            status = self._click_reserve_button_v2() 

            if status == "ALREADY_DONE":
                print(f"🔒 {self.WHO_AM_I} is already booked. Exiting quietly.")
                return "SUCCESS_SILENT"

            if status == "CLICKED":
                if "pickleball" in (self.TARGET_CLASS or "").lower():
                    self._handle_waiver()
                
                # Finalizing the click
                self._click_finish()
                
                if self._verify_confirmation():
                    self.send_notification("Lifetime Bot - Success", f"✅ Class reserved!\n\n{class_details}")
                    return "SUCCESS_NEW"

            return "RETRY"

        except Exception as e:
            print(f"❌ Error for {self.WHO_AM_I}: {e}")
            return "RETRY"
        finally:
            try:
                self.driver.quit()
            except:
                pass

    def _click_reserve_button_v2(self) -> str:
        """Helper to determine if we need to click or if we are already done."""
        time.sleep(4) # Wait for page JS to settle
        
        # 1. Try to find the PRIMARY button using its specific Life Time ID
        try:
            # We use a 10-second explicit wait here to be safe
            primary_button = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button[data-test-id='reserveButton']"))
            )
            txt = (primary_button.text or "").strip()
            print(f"DEBUG: Main Button Found: '{txt}'")
            
            # Use exact phrase matching to avoid rogue buttons
            if txt in ["Cancel Reservation", "Leave Waitlist"]:
                return "ALREADY_DONE"
            
            if "Reserve" in txt or "Waitlist" in txt:
                self.driver.execute_script("arguments[0].scrollIntoView();", primary_button)
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", primary_button)
                return "CLICKED"
        except Exception:
            print("⚠️ Primary 'reserveButton' ID not found, checking specific text buttons...")

        # 2. Fallback: Search for buttons with ONLY these exact phrases
        # This prevents the bot from accidentally clicking "Cancel" on a search filter
        target_phrases = ["Reserve", "Add to Waitlist", "Cancel Reservation", "Leave Waitlist"]
        
        buttons = self.driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            txt = (button.text or "").strip()
            if txt in target_phrases:
                print(f"DEBUG: Found Specific Action Button: '{txt}'")
                if "Cancel" in txt or "Leave" in txt:
                    return "ALREADY_DONE"
                else:
                    self.driver.execute_script("arguments[0].click();", button)
                    return "CLICKED"
        
        # If we reach here, we found nothing. We should NOT assume it's booked.
        # We raise an error so the main loop triggers a RETRY.
        raise Exception("No reservation-related buttons found on the page yet.")

# ==============================
# MAIN LOOP HELPERS
# ==============================

def cleanup_chrome():
    """Kill any leftover Chrome / ChromeDriver processes (CI safety)."""
    try:
        os.system("pkill -f chrome || true")
        os.system("pkill -f chromedriver || true")
    except Exception:
        pass


def wait_until_booking_window():
    """Block until 10:01 AM CST."""
    now = datetime.datetime.now(CST)

    start = now.replace(
        hour=BOOKING_START_TIME.hour,
        minute=BOOKING_START_TIME.minute,
        second=0,
        microsecond=0
    )

    if now < start:
        sleep_seconds = (start - now).total_seconds()
        print(f"⏳ Waiting {int(sleep_seconds)} seconds until booking window (10:01 CST)")
        time.sleep(sleep_seconds)

    print("✅ Booking window open")

# ==============================
# 🔔 STARTUP NOTIFICATION (ADDED)
# ==============================

def send_startup_notification():
    try:
        bot = LifetimeReservationBot()
        who = os.getenv("WHO_AM_I", "Unknown") # FIXED: Use os.getenv instead of self
        now_cst = datetime.datetime.now(CST).strftime("%Y-%m-%d %I:%M:%S %p CST")
        bot.send_telegram(
            f"🚀 <b>Lifetime Bot Started for {who}</b>\n"
            f"Time: {now_cst}\n"
            f"Status: Initialized and waiting for booking window."
        )
    except Exception as e:
        print(f"⚠️ Could not send startup notification: {e}")

def main():
    who = os.getenv("WHO_AM_I", "Unknown")
    print(f"🚀 Lifetime Bot starting for {who}")

    # --- ADD JITTER ---
    # This prevents your bot and your wife's bot from hitting 
    # the login page at the exact same second.
    jitter = random.randint(1, 15)
    print(f"⏳ Staggering start by {jitter} seconds to avoid login collision...")
    time.sleep(jitter)

    send_startup_notification()

    # Wait until booking window (10:01)
    wait_until_booking_window()

    while True:
        now = datetime.datetime.now(CST)
        cutoff = now.replace(hour=BOOKING_CUTOFF_TIME.hour, minute=BOOKING_CUTOFF_TIME.minute, second=0, microsecond=0)

        if now >= cutoff:
            print("🚨 Cutoff reached. Sending failure notification.")
            bot = LifetimeReservationBot()
            bot.send_notification("Lifetime Bot - Failed", f"❌ {who}: Failed to book by 10:15 AM CST.")
            return

        # Check for valid day inside the loop as well
        if datetime.datetime.now(CST).weekday() not in [6, 0, 2, 3]:
            print("❌ Not a booking day. Exiting.")
            return

        cleanup_chrome()

        try:
            bot = LifetimeReservationBot()
            result = bot.reserve_class()
            
            # SUCCESS_NEW: Just booked it (Sent notification)
            # SUCCESS_SILENT: Already booked (No notification sent)
            if result in ["SUCCESS_NEW", "SUCCESS_SILENT"]:
                print(f"✅ {who}: Task finished successfully.")
                return
        except Exception as e:
            print(f"⚠️ Loop error: {e}")

        print(f"🔁 Retrying in {RETRY_INTERVAL_SECONDS} seconds...")
        time.sleep(RETRY_INTERVAL_SECONDS)

if __name__ == "__main__":
    send_early_startup_notification()
    main()
