from app.services.importer import preview_messages


def test_preview_extracts_a_job_and_counts_irrelevant_lines():
    jobs, ignored = preview_messages("初中数学家教，周末上课，薪资 150元/小时，地址在海淀区\n今晚聚餐")
    assert len(jobs) == 1
    assert jobs[0]["subject"] == "数学"
    assert jobs[0]["grade"] == "初中"
    assert jobs[0]["salary"] == 150
    assert jobs[0]["location"] == "海淀区"
    assert ignored == 1


def test_blank_input_is_safe():
    assert preview_messages(" \n") == ([], 0)
