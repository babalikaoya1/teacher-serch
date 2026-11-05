from app.services.importer import preview_messages


def test_preview_extracts_a_job_and_counts_irrelevant_lines():
    jobs, ignored = preview_messages("初中数学家教，周末上课，薪资 150元/小时，地址在海淀区\n今晚聚餐")
    assert len(jobs) == 1
    assert jobs[0]["subject"] == "数学"
    assert jobs[0]["grade"] == "初中"
    assert jobs[0]["salary"] == 150
    assert jobs[0]["location"] == "海淀区"
    assert jobs[0]["schedule"] == "周末上课"
    assert ignored == 1


def test_blank_input_is_safe():
    assert preview_messages(" \n") == ([], 0)


def test_multiline_offline_order_keeps_hourly_salary_and_source_group():
    sample = """顺义区线下家教
🌸🌸BJ06801407（近期+暑假）#周薪750
联系地址：#顺义区首创·禧瑞墅4期
年级性别：一年级，女
辅导科目：作业辅导 英语
学员情况：她拼音没学好 认字太少了
时间安排：近期开始 #周一至周五 五点半开始 一周5次 一次1.5小时
教员要求：男女老师不限 经验丰富 有责任心 有耐心
薪资待遇：100元/小时"""
    jobs, ignored = preview_messages(sample, source_group="顺义家教群")

    assert ignored == 0
    assert len(jobs) == 1
    job = jobs[0]
    assert job["location"] == "顺义区首创·禧瑞墅4期"
    assert job["teaching_mode"] == "线下"
    assert job["grade"] == "一年级"
    assert job["gender"] == "女"
    assert job["subject"] == "作业辅导 英语"
    assert job["salary"] == 100
    assert job["salary_basis"] == "hour"
    assert job["salary_unit"] == "元/小时"
    assert job["order_code"] == "BJ06801407"
    assert job["source_group"] == "顺义家教群"


def test_multiline_online_order_parses_starting_hourly_rate():
    sample = """【编号】：LXR签-瑞丰
【地址】：线上
【年级】：初二
【科目】：英语
【课次】：一周一次 2h
【要求】：主要是讲完型填空，熟悉北京考题
【时薪】：130+/h"""
    jobs, _ = preview_messages(sample, source_group="线上订单群")

    assert len(jobs) == 1
    assert jobs[0]["teaching_mode"] == "线上"
    assert jobs[0]["location"] == "线上"
    assert jobs[0]["grade"] == "初二"
    assert jobs[0]["subject"] == "英语"
    assert jobs[0]["salary"] == 130
    assert jobs[0]["salary_basis"] == "hour"
    assert jobs[0]["salary_is_minimum"] is True
    assert jobs[0]["order_code"] == "LXR签-瑞丰"


def test_concatenated_orders_split_without_blank_lines_and_extract_address_gender_salary():
    sample = """A 80903 T
门头沟九龙东苑
六年级数学
男孩儿
每周1次，2h（周一晚6:30-8:30）
时薪500/2h
WH0710041
西城马连道常青藤嘉园
初二物理
女孩儿
每周2次，2h/次（周中晚7-9）
时薪300+/h
A 26033101
朝阳门豆瓣小区
初一数学英语
男孩儿
每周1次，2h（周日上午）
时薪300/h
25113001
东三环世贸公园
初二物理
女孩儿
每周1次，2h（周日上午）
时薪300/h"""
    jobs, ignored = preview_messages(sample)

    assert ignored == 0
    assert len(jobs) == 4
    assert [job["location"] for job in jobs] == ["门头沟九龙东苑", "西城马连道常青藤嘉园", "朝阳门豆瓣小区", "东三环世贸公园"]
    assert [job["gender"] for job in jobs] == ["男", "女", "男", "女"]
    assert jobs[0]["salary"] == 500
    assert jobs[0]["salary_basis"] == "session"
    assert jobs[1]["salary_is_minimum"] is True
    assert [job["order_code"] for job in jobs] == ["A 80903 T", "WH0710041", "A 26033101", "25113001"]
