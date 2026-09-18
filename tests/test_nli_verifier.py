from grounded_rag.guard.nli_verifier import NLIVerifier, numbers, numbers_supported, premise_views

P98 = (
    "Điều 98. Tiền lương làm thêm giờ\n"
    "1. Người lao động làm thêm giờ được trả lương như sau:\n"
    "a) Vào ngày thường, ít nhất bằng 150%;\n"
    "b) Vào ngày nghỉ hằng tuần, ít nhất bằng 200%;"
)


def test_numbers_ignore_leading_zeros_and_thousand_separators():
    assert numbers("08 giờ trong 01 ngày, 1.000 đồng") == {"8", "1", "1000"}


def test_a_number_the_premise_never_states_is_not_supported():
    assert numbers_supported(P98, "Ngày thường ít nhất bằng 150%.")
    assert not numbers_supported(P98, "Ngày thường ít nhất bằng 160%.")


def test_each_list_item_is_read_with_its_heading_and_lead_in():
    views = premise_views(P98)
    assert views[0] == P98
    assert (
        "Điều 98. Tiền lương làm thêm giờ\n"
        "1. Người lao động làm thêm giờ được trả lương như sau:\n"
        "a) Vào ngày thường, ít nhất bằng 150%;"
    ) in views
    assert len(views) == 3


def test_sentences_of_one_clause_become_views_of_their_own():
    premise = "Điều 111. Nghỉ hằng tuần\n1. Mỗi tuần nghỉ 24 giờ. Trường hợp đặc biệt nghỉ 04 ngày."
    assert "Điều 111. Nghỉ hằng tuần\nTrường hợp đặc biệt nghỉ 04 ngày." in premise_views(premise)


def test_a_single_line_premise_is_its_only_view():
    assert premise_views("Phải báo trước 45 ngày.") == ["Phải báo trước 45 ngày."]


def test_verifier_takes_the_best_view_and_zeroes_invented_numbers(monkeypatch):
    nli = NLIVerifier("unused")
    seen = []

    def raw(premise, hypothesis):
        seen.append(premise)
        return 0.9 if premise.endswith("150%;") else 0.2

    monkeypatch.setattr(nli, "raw_entailment", raw)
    assert nli.entailment(P98, "Ngày thường ít nhất 150%.") == 0.9
    seen.clear()
    assert nli.entailment(P98, "Ngày thường ít nhất 170%.") == 0.0
    assert seen == []  # no model call for a claim the rule already rejects


def test_a_rule_and_its_exception_joined_by_a_semicolon_are_separate_views():
    premise = ("Điều 29. Chuyển người lao động\n1. Không được quá 60 ngày trong 01 năm; "
               "trường hợp quá 60 ngày thì phải được đồng ý.")
    assert "Điều 29. Chuyển người lao động\n1. Không được quá 60 ngày trong 01 năm;" in (
        premise_views(premise)
    )
