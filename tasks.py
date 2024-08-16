from robocorp.tasks import task
from robocorp import workitems
import logging
from bs4 import BeautifulSoup
import requests
from typing import Literal, Union
from datetime import datetime
import re
from dateutil.relativedelta import relativedelta
from xlsxwriter import Workbook
import os

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
    # Defining variables
    url_template = "https://www.latimes.com/search?q={}&s=1"
    url_template_type = "https://www.latimes.com/search?q={}&f1={}&s=1"
    articles = []
    in_date_range = True

    url = url_template.format(search_term)
    if news_type:
        type = TYPE_DICT.get(news_type)
        url = url_template_type.format(search_term, type)
    logger.info(f"Search Url: {url}")

    # Getting date range
    current_date = datetime.now()
    start_date = datetime(current_date.year, current_date.month, 1)
    if months > 1:
        start_date = start_date - relativedelta(months=(months-1))
    logger.info(f"Date range is from {start_date} to {current_date}")

    while True:
        page = requests.get(url, headers=headers)
        if page.status_code != 200:
            logger.error(f"Error when searching for news, status code: {page.status_code}")
            raise("Error when searching for news")
        logger.info(f"Search successfull")

        soup = BeautifulSoup(page.text, "html.parser")
        cards = soup.find_all('div', 'promo-wrapper')

        for card in cards:
            info = get_card_info(card, search_term)
            if start_date <= info["date"] <= current_date:
                articles.append(info)
            else:
                logger.info(f"Article {info['title']} outsite range found: {info['date']}")
                in_date_range = False
                break
        
        if not in_date_range:
            logger.info("Exiting main loop")
            break

        # Get next page
        logger.info("Getting next page")
        next_page = soup.find('div', 'search-results-module-next-page')
        if next_page is None:
            logger.info(f"Could not find new page")
            break
        
        try:
            url = next_page.find("a").get("href")
            logger.info(f"New page found, URL: {url}")
        except AttributeError:
            logger.info(f"Could not find new page")
            break
        
    return articles

def get_card_info(card, search_term):
    
    title = card.find("h3", "promo-title").text
    description = card.find("p", 'promo-description').text
    timestamp = card.find("p", "promo-timestamp").get("data-timestamp")
    # format_string = "%B %d, %Y"

    datetime_object = datetime.fromtimestamp(int(timestamp)/ 1000)
    # datetime_object = datetime.strptime(date_str, format_string)
    # Getting the first image for the card
    pictures = card.find("img", "image")
    if pictures is None:
        filename = "Picture not found"
    else:
        pictures = pictures.get("srcset").split(",")
        picture = pictures[0]
        picture_url = picture.split(" ")[0]
        resposne = requests.get(picture_url)
        if resposne.status_code != 200:
            raise("Error when getting image")
        # Gettting picture extension
        file_extension = resposne.headers["Content-Type"].split("/")[-1]
        safe_title = re.sub(r'[<>"/\\|?*]', '_', title).rstrip()
        filename = f"{safe_title}.{file_extension}"
        open(f"./output/{filename}", 'wb').write(resposne.content)
    
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
    headers = ["title", "date", "description", "pic_filename", "count", "has_money"]
    filepath = f"./output/articles-{search_term}.xlsx"
    wb=Workbook(filepath)
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
        print("Received payload:", item.payload)

        # Access the specific values from the work item
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
        search_term = "brexit"
        news_type = None
        months = 4

    articles = search_news(search_term, news_type, months)
    if not articles:
        # Timeout error
        logger.error("Timeout error, returning false")
        return False
    
    create_excel_file(articles, search_term)
    logger.info("Exiting task")


if __name__ == "__main__":
    main_task()