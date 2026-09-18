from grounded_rag.guard.claim_splitter import split_claims


def test_splits_sentences_and_keeps_citations_with_their_claim():
    claims = split_claims("Phải báo trước 45 ngày [C1]. Không áp dụng với thử việc [C2].")
    assert len(claims) == 2
    assert claims[0].citations == ["C1"]
    assert claims[1].citations == ["C2"]


def test_a_period_inside_dieu_35_does_not_end_a_sentence():
    # the whole reason this module exists
    claims = split_claims("Theo Điều 35. khoản 1, phải báo trước 45 ngày [C1].")
    assert len(claims) == 1


def test_claim_without_citation_keeps_an_empty_list():
    assert split_claims("Một khẳng định không nguồn.")[0].citations == []


def test_a_citation_after_the_full_stop_stays_with_its_own_sentence():
    # models write "... ngày. [C1]" about as often as "... ngày [C1]."
    claims = split_claims("Phải báo trước 45 ngày. [C1] Không áp dụng với thử việc. [C2]")
    assert [c.citations for c in claims] == [["C1"], ["C2"]]
    assert claims[1].text == "Không áp dụng với thử việc."


def test_list_items_are_claims_and_their_numbers_are_not():
    answer = "Theo tài liệu:\n1. Phải báo trước 45 ngày [C1]\n- Nghỉ hằng năm 12 ngày [C2]"
    claims = split_claims(answer)
    assert [(c.text, c.citations) for c in claims] == [
        ("Phải báo trước 45 ngày", ["C1"]),
        ("Nghỉ hằng năm 12 ngày", ["C2"]),
    ]


def test_lower_case_khoan_does_not_end_a_sentence_either():
    claims = split_claims("Theo khoản 1. Điều 35, phải báo trước 45 ngày [C1].")
    assert len(claims) == 1
    assert claims[0].text.startswith("Theo khoản 1. Điều 35")


def test_the_guards_output_splits_back_into_the_same_claims():
    # eval re-splits the final answer, which the policy re-joins from kept claims
    from grounded_rag.guard.policy import _join

    claims = split_claims("Phải báo trước 45 ngày [C1]. Không áp dụng với thử việc [C2].")
    again = split_claims(_join(claims))
    assert [(c.text, c.citations) for c in again] == [(c.text, c.citations) for c in claims]


def test_a_bracketed_answer_is_unwrapped_not_deleted():
    # qwen2.5:3b writes the number it found in brackets; deleting the brackets'
    # content left "tối đa là." and the guard refused a correct answer
    claims = split_claims("Thời gian thử việc tối đa là [60 ngày] [C1]. Trừ tối đa [30%] [C2].")
    assert [c.text for c in claims] == ["Thời gian thử việc tối đa là 60 ngày.", "Trừ tối đa 30%."]


def test_an_article_number_in_brackets_is_not_a_claim_or_part_of_one():
    # what qwen2.5:3b wrote for a third of the answerable questions
    assert split_claims("[Điều 105, Khoản 1][C1]") == []
    assert [c.text for c in split_claims("[CR1] Không quá 04 giờ [C1].")] == ["Không quá 04 giờ."]
    assert [c.text for c in split_claims("[TRẢ LỜI] Là 30 ngày [C1].")] == ["Là 30 ngày."]
    assert [c.text for c in split_claims("Theo [khoản 2 Điều 46], 10 ngày [C1].")] == [
        "Theo khoản 2 Điều 46, 10 ngày."
    ]
    claims = split_claims("[Điều 26] Lương thử việc ít nhất bằng 85% [C1].")
    assert [(c.text, c.citations) for c in claims] == [("Lương thử việc ít nhất bằng 85%.", ["C1"])]


def test_an_echoed_answer_slot_is_dropped():
    claims = split_claims("Câu trả lời: Tối đa 08 giờ một ngày [C2].")
    assert [(c.text, c.citations) for c in claims] == [("Tối đa 08 giờ một ngày.", ["C2"])]


def test_a_cited_sentence_ending_in_a_colon_is_still_a_claim():
    assert len(split_claims("Người lao động được nghỉ trong các trường hợp sau [C1]:")) == 1
