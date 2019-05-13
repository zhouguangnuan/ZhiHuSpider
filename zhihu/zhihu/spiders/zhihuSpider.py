# -*- coding: utf-8 -*-
import scrapy
import re
from zhihu.items import ZhihuQuestionItem, ZhihuAnswerItem
import json
from scrapy.utils.project import get_project_settings
from scrapy.http.cookies import CookieJar
import base64
import urllib
from urllib import parse
import time
import os
from xml.sax.saxutils import unescape,escape
from pyquery import PyQuery as pq
import uuid
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

class ZhiHuSpider(scrapy.Spider):

    name = "zhihu"
    start_urls = ['https://zhihu.com']
    allowed_domains = ['www.zhihu.com']

    setting = get_project_settings()
    headers = setting['DEFAULT_REQUEST_HEADERS']
    post_data = setting['POST_DATA']
    question_count = setting['QUESTION_COUNT']
    answer_count = setting['ANSWER_COUNT_PER_QUESTION']
    answer_offset = setting['ANSWER_OFFSET']
    img_dir = setting['IMG_DIR']
    show_img_path = setting['SHOW_IMG_PATH']


    login_header = {
        "content-type": "application/x-www-form-urlencoded",
        "x-zse-83" : "3_1.1",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.139 Safari/537.36',
        'Referer': 'https://www.zhihu.com',
        'HOST': 'www.zhihu.com',
        ':authority': 'www.zhihu.com'
    }


    # 翻页请求问题相关
    next_page = 'https://www.zhihu.com/api/v3/feed/topstory?action_feed=True&limit=10&' \
                'session_token={0}&action=down&after_id={1}&desktop=true'

    session_token = ''
    after_id = 5
    limit = 6
    page_number = 2
    cookies = {}

    option = webdriver.ChromeOptions()
    option.add_experimental_option('excludeSwitches', ['enable-automation'])

    # 点击查看更多答案触发的url
    more_answer_url = 'https://www.zhihu.com/api/v4/questions/{0}/answers?include=data[*].is_normal,admin_closed_comment' \
                      ',reward_info,is_collapsed,annotation_action,annotation_detail,collapse_reason,is_' \
                      'sticky,collapsed_by,suggest_edit,comment_count,can_comment,content,editable_conte' \
                      'nt,voteup_count,reshipment_settings,comment_permission,created_time,updated_time,' \
                      'review_info,relevant_info,question,excerpt,relationship.is_authorized,is_author,v' \
                      'oting,is_thanked,is_nothelp;data[*].mark_infos[*].url;data[*].author.follower_cou' \
                      'nt,badge[?(type=best_answerer)].topics&offset={1}&limit={2}&sort_by=default'

    def start_requests(self):

        caps = DesiredCapabilities.CHROME
        caps['loggingPrefs'] = {'performance': 'ALL'}

        driver = webdriver.Chrome("F:\chromedriver\chromedriver.exe", options=self.option,desired_capabilities=caps)

        driver.get("https://www.zhihu.com/signin?next=%2F")

        input('请在浏览器上登陆后，请点击按任意键开始：')

        logs = [json.loads(log['message'])['message']['params'] for log in driver.get_log('performance')]

        # 从请求信息中提取session_key
        requestUrl = ''
        for log in logs:
            if 'request' in log:
                try:
                    if log['request']['url'].find('session_token') != -1:
                        requestUrl = log['request']['url']
                        break
                except:
                    continue

        if requestUrl == '':
            print('未获取到关键信息')

        # 获取session_token
        self.session_token = parse.parse_qs(urllib.parse.urlparse(requestUrl).query).get('session_token')[0]
        self.cookies = driver.get_cookies()
        # 登录完成，并获取到所有关键信息
        print("登录完成............")
        # 获取当前页的接口返回

        yield scrapy.Request(self.parse_page_url(), headers=self.headers, cookies=self.cookies,
                             callback=self.get_page_data)

    def parse_page_url(self,):
        pageurl = "https://www.zhihu.com/api/v3/feed/topstory/recommend?"

        urldata = {}
        urldata['session_token'] = self.session_token
        urldata['after_id'] = self.after_id
        urldata['desktop'] = 'true'
        urldata['page_number'] = self.page_number
        urldata['limit'] = self.limit
        urldata['action'] = 'down'

        url = pageurl + urllib.parse.urlencode(urldata)
        print(url)

        return url

    def get_page_data(self, response):
        """ 获取更多首页问题 """
        question_url = 'https://www.zhihu.com/question/{0}'
        questions = json.loads(response.text)
        # 更新页数 及最后的id
        self.page_number = self.page_number + 1
        self.after_id = self.after_id + self.limit

        for que in questions['data']:
            question_id = re.findall(r'(\d+)', que['target']['question']['url'])[0]
            yield scrapy.Request(question_url.format(question_id), headers=self.headers, cookies=self.cookies,
                                 callback=self.parse_question)

    def parse(self, response):
        """ 获取首页问题 """
        # /question/19618276/answer/267334062
        question_urls = response.xpath('//a[@data-za-detail-view-element_name="Title"]/@href').extract()

        question_urls = [parse.urljoin(response.url, url) for url in question_urls]
        print(question_urls)

        # # 翻页用到的session_token 和 authorization都可在首页源代码找到
        self.session_token = re.findall(r'session_token=([0-9,a-z]{32})', response.text)[0]
        # auto = re.findall(r'carCompose&quot;:&quot;(.*?)&quot', response.text)[0]
        # self.headers['authorization'] = 'Bearer ' + auto
        #
        # # 首页第一页问题
        for url in question_urls:
            question_detail = url
            yield scrapy.Request(question_detail, headers=self.headers, callback=self.parse_question)
        #
        # 获取指定数量问题
        n = len(question_urls)
        while n < self.question_count:
            yield scrapy.Request(self.next_page.format(self.session_token, n), headers=self.headers,
                                 callback=self.get_more_question)
            n += 10

    def saveimgs(self,img_url):
        """保存图片"""
        image_path = img_url.split('.')
        extension = image_path.pop()
        if extension in ['jpg','png','gif','jpeg']:
            if len(extension) > 3:
                extension = 'jpg'
            u = urllib.request.urlopen(img_url)
            data = u.read()
            # 上层目录 以日期命名
            parent_dir = str(time.strftime("%Y%m%d"))
            # 实际保存路径
            path = self.img_dir + parent_dir
            # 判断路径是否存在
            isExists = os.path.exists(path)
            if not isExists:
                os.makedirs(path)
            # 生成随机文件名
            # name = str(random.randint(1000000, 9999999))
            name = str(uuid.uuid4())
            file_name = path + '/' + name
            f = open(file_name + '.' + extension, 'wb')
            f.write(data)
            f.close()
            # 返回展示在网页的文件路径
            return self.show_img_path + parent_dir + '/' + name + '.' + extension
        else:
            return False

    def parse_question(self, response):
        """ 解析问题详情及获取指定范围答案 """
        item = ZhihuQuestionItem()

        item['name'] = response.xpath('//meta[@itemprop="name"]/@content').extract()[0]
        item['url'] = response.xpath('//meta[@itemprop="url"]/@content').extract()[0]
        item['keywords'] = response.xpath('//meta[@itemprop="keywords"]/@content').extract()[0]
        item['answer_count'] = response.xpath('//meta[@itemprop="answerCount"]/@content').extract()[0]
        item['comment_count'] = response.xpath('//meta[@itemprop="commentCount"]/@content').extract()[0]
        item['flower_count'] = response.xpath('//meta[@itemprop="zhihu:followerCount"]/@content').extract()[0]
        item['date_created'] = response.xpath('//meta[@itemprop="dateCreated"]/@content').extract()[0][0:19].replace('T',' ')

        count_answer = int(item['answer_count'])

        question_id = int(re.match(r'https://www.zhihu.com/question/(\d+)', response.url).group(1))

        item['question_id'] = question_id
        print(item)

        yield item



        # 从指定位置开始获取指定数量答案
        if count_answer > self.answer_count:
            count_answer = self.answer_count
        n = self.answer_offset
        while n + 20 <= count_answer:
            yield scrapy.Request(self.more_answer_url.format(question_id, n, n + 10), headers=self.headers,
                                 callback=self.parse_answer)
            n += 20


    def parse_answer(self, response):
        """ 解析获取到的指定范围答案 """
        text = response.text
        answers = json.loads(text)

        for ans in answers['data']:
            item = ZhihuAnswerItem()
            item['answer_id'] = ans['id']
            item['question_id'] = ans['question']['id']
            item['author'] = ans['author']['name']
            # https://www.zhihu.com/question/266730428/answer/314851560
            item['ans_url'] = 'https://www.zhihu.com/question/' + str(item['question_id']) + '/answer/' + str(item['answer_id'])
            item['comment_count'] = ans['comment_count']
            item['upvote_count'] = ans['voteup_count']
            item['excerpt'] = ans['excerpt']
            if item['upvote_count'] > self.setting['MIN_UPVOTE_COUNT']:
                item['content'] = self.parse_content(ans['content'])
            item['content'] = ans['content']
            yield item

    def parse_content(self,content):
        # 反转义html
        content = unescape(content)
        # 使用pyquery解析html（类似js中jquery）
        # 知乎中所有图片被<figure></figure>标签嵌套而导致无法正常显示在页面
        d = pq(content)
        print(content)
        index = 0
        # 图片均由<figure></figure>此标签包裹
        for figure in d.items('figure'):
            # 获取figure中的img标签
            img = figure.find('noscript img')
            print(img)
            # 获取图片url
            src = pq(img).attr('src')
            # 获取保存后图片的本地url
            new_src = self.saveimgs(src)
            new_img = ''
            if new_src:
                    # 替换原来的图片链接
                    new_img = str(img).replace(src, new_src)
            print(new_img)
            content = content.replace(str(figure), new_img)
            index = index + 1
        # 返回值
        return content

    # def check_human(self,response):
    #     """解决知乎检测账号流量异常后的验证操作"""
    #     unhuman_captcha = response.xpath('//meta[@itemprop="name"]/@content').extract()
    #     #是否进入了 检测程序提交页面
    #     #https://www.zhihu.com/account/unhuman?type=unhuman&message=系统检测到您的帐号或IP存在异常流量，请进行验证用于确认这些请求不是自动程序发出的
    #     if len(unhuman_captcha) > 0 :
    #
    #
    #     else :
    #         # 否则返回true  接着爬
    #         return True





