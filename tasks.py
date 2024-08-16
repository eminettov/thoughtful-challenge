from robocorp.tasks import task
from robocorp import workitems
import logging
from typing import Literal, Union
from datetime import datetime
import re
from dateutil.relativedelta import relativedelta
from xlsxwriter import Workbook
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
import requests
import os
import time


chrome_options = Options()
chrome_options.add_argument("--headless")  # Run headless Chrome for no UI
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

logger = logging.getLogger(__name__)

NEWS_TYPE = Union[Literal["story", "newsletter", "video", "gallery", "live_blog"], None]

TYPE_DICT = {
    "story": "0000016a-ea2d-db5d-a57f-fb2dc8680000",
    "newsletter": "8fd31d5a-5e1c-3306-9f27-6edc9b08423e", 
    "video": "431a5800-2fb3-3b19-9801-23dc4b0ff9a8", 
    "gallery": "8bef3534-a8b9-3d63-8ef0-f2da41b84783", 
    "live_blog": "9f352849-b032-3124-8c90-1c41a434a7c4"
}
    
headers = {
    'accept': '*/*',
    'accept-encoding': 'gzip, deflate, br',
    'accept-language': 'en-US,en;q=0.9',
    'referer': 'https://www.google.com',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.83 Safari/537.36 Edg/85.0.564.44'
}

def search_news(search_term: str, news_type: NEWS_TYPE = None, months: int = 1):
    try:
        # Defining variables
        articles = []
        in_date_range = True
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        logger.info(f"Opening web site: https://www.latimes.com/")
        driver.get('https://www.latimes.com/')  
        logger.info("Website openned")

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CLASS_NAME, 'page-main'))
        )

        search_button = driver.find_element(By.CSS_SELECTOR, 'button[data-element="search-button"]')
        search_button.click()

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'div[data-element="search-overlay"]'))
        )

        logger.info(f"Searching for term: {search_term}")
        search_input = driver.find_element(By.CSS_SELECTOR, 'input[data-element="search-form-input"]')
        search_input.send_keys(search_term)
        
        search_submit_button = driver.find_element(By.CSS_SELECTOR, 'button[data-element="search-submit-button"]')
        search_submit_button.click()

        WebDriverWait(driver, 10).until(
                lambda driver: driver.execute_script('return document.readyState') == 'complete'
            )
        
        if news_type:
            type = TYPE_DICT.get(news_type)
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, 'search-results-module-main'))
            )
            filter_checkbox = driver.find_element(By.CSS_SELECTOR, f'input[value="{type}"]')
            filter_checkbox.click()

        # Getting date range
        current_date = datetime.now()
        start_date = datetime(current_date.year, current_date.month, 1)
        if months > 1:
            start_date = start_date - relativedelta(months=(months-1))
        logger.info(f"Date range is from {start_date} to {current_date}")

        while True:
            logger.info(f"Search successfull, getting articles from page")

            sort_select = Select(driver.find_element(By.CLASS_NAME, 'select-input'))
            sort_select.select_by_value('1')

            WebDriverWait(driver, 10).until(
                lambda driver: driver.execute_script('return document.readyState') == 'complete'
            )

            retry = 0
            max_retries = 3
            while retry < max_retries:
                cards = driver.find_elements(By.CLASS_NAME, 'promo-wrapper')
                logger.info(f"CARDS: {cards}")
                try:
                    for card in cards:
                        logger.info(f"CARD: {card}")
                        info = get_card_info(card, search_term)

                        if start_date <= info["date"] <= current_date:
                            articles.append(info)
                        else:
                            logger.info(f"Article {info['title']} outsite range found: {info['date']}")
                            in_date_range = False
                            break
                    break
                except StaleElementReferenceException:
                    retry += 1
                    time.sleep(1)  # Small delay before retrying
                    if retry == max_retries:
                        raise StaleElementReferenceException


            if not in_date_range:
                logger.info("Exiting main loop")
                break

            # Get next page
            logger.info("Getting next page")
            # Navigate to the next page
            next_page_button = driver.find_element(By.CLASS_NAME, 'search-results-module-next-page')
            # Check if the "Next" button is inactive (no <a> tag present, only <svg>)
            if next_page_button.find_elements(By.CSS_SELECTOR, 'svg[data-inactive]'):
                logger.info(f"Could not find new page")
                break

            next_button = next_page_button.find_element(By.TAG_NAME, 'a')
            next_button.click()
    except TimeoutException:
        logger.error("Timeout error, page cound not load")
        return False
        
    return articles

def get_card_info(card, search_term):
    title = card.find_element(By.CSS_SELECTOR, "h3.promo-title").text
    description = card.find_element(By.CSS_SELECTOR, 'p.promo-description').text
    timestamp = card.find_element(By.CSS_SELECTOR, "p.promo-timestamp").get_attribute("data-timestamp")
    datetime_object = datetime.fromtimestamp(int(timestamp)/ 1000)
    try:
        pictures = card.find_element(By.CSS_SELECTOR, "img.image").get_attribute("srcset").split(",")
        picture = pictures[0]
        picture_url = picture.split(" ")[0]
        resposne = requests.get(picture_url)
        if resposne.status_code != 200:
            raise("Error when getting image")
        # Gettting picture extension
        file_extension = resposne.headers["Content-Type"].split("/")[-1]
        # removing characters that can break the path
        safe_title = re.sub(r'[<>"/\\|?*]', '_', title).rstrip()
        filename = f"{safe_title}.{file_extension}"
        open(f"output/{safe_title}", 'wb').write(resposne.content)
    except NoSuchElementException:
        logger.warning(f"Could not find picture")
        filename = "Picture not found"
    
    count = title.count(search_term) + description.count(search_term)
    has_money = check_money_patters(title, description)
     
    return {
        "title": title,
        "description": description,
        "date": datetime_object,
        "pic_filename": filename,
        "count": count,
        "has_money": has_money,
    }

def check_money_patters(title: str, description: str):
    money_pattern = re.compile(r'''
        (\$\d{1,3}(,\d{3})*(\.\d{2})?) |         # Matches $11.1 or $111,111.11
        (\d+\s?(dollars|USD))                    # Matches 11 dollars or 11 USD
    ''', re.VERBOSE)

    return bool(money_pattern.search(title)) or bool(money_pattern.search(description))

def create_excel_file(articles: list, search_term):
    logger.info("Creating excel")
    headers = ["title", "date", "description", "pic_filename", "count", "has_money"]
    wb=Workbook(f"./output/articles-{search_term}.xlsx")
    ws=wb.add_worksheet()    

    if len(articles) == 0:
        ws.write(0, 0, "No articles found for the date range")

    else:
        # Writing the columns mane to the excel file
        for index, header in enumerate(headers):
            ws.write(0, index, header)

        for row_index, article in enumerate(articles, start=1):
            for key, value in article.items():
                col = headers.index(key)
                if key == "date":
                    value = value.strftime('%m/%d/%Y')
                ws.write(row_index, col, value)

    wb.close()

@task
def main_task():
    logging.basicConfig(level=logging.INFO)
    logger.info("Getting INPUT values")

    in_robot = os.getenv("IN_ROBOT", False)
    logger.info(f"IN_ROBOT: {in_robot}")
    if in_robot:
        item = workitems.inputs.current
        logger.info(f"Received payload: {item.payload}")

        search_term = item.payload.get("SEARCH_TERM", None)
        if search_term is None:
            logger.error("SEARCH_TERM can not be None")
            return False
        
        news_type = item.payload.get("NEWS_TYPE", None)
        months = item.payload.get("MONTHS", None)
        if isinstance(months, str):
            # Converting monsths to a int
            months = int(months)
    else:
        search_term = "olympics"
        news_type = None
        months = 1

    articles = search_news(search_term, news_type, months)
    if not articles:
        return False
    
    create_excel_file(articles, search_term)
    logger.info("Exiting task")


if __name__ == "__main__":
    main_task()