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
        ("Theo tài liệu:", []),
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
