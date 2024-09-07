import requests
from bs4 import BeautifulSoup
"""
<span data-hk="9.92" class="pt-[3px]" data-marker-title="">Level 94 Crit Lightning Strike of Arcing Deadeye</span>


"""

url = "http://localhost/pob.html"

r = requests.get(url)

soup = BeautifulSoup(r.text, 'html.parser')

title = soup.find('span', attrs={'data-hk': '9.92'})
title = title.text
print(title)