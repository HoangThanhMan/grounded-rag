"""Does the NLI model catch Vietnamese claims that keep
most of the wording but change a number, the subject or a condition - and
does it let correct restatements of a long clause through?

    python scripts/nli_probe.py                                   # needs `models`
    python scripts/nli_probe.py --model joeddav/xlm-roberta-large-xnli

Two columns per pair: `raw` is the model reading the whole clause, `guard` is
what the verifier returns - best view of the clause, zero for an invented
number (grounded_rag/guard/nli_verifier.py). The premises are real clauses
from the corpus; the "long clause" pairs are correct sentences the first
100-question run rejected.
"""

from __future__ import annotations

import argparse

from grounded_rag.config import settings
from grounded_rag.guard.nli_verifier import NLIVerifier

P35 = (
    "Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động của người lao động\n"
    "1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động nhưng phải báo trước "
    "ít nhất 45 ngày nếu làm việc theo hợp đồng lao động không xác định thời hạn."
)
P105_1 = (
    "Điều 105. Thời giờ làm việc bình thường\n"
    "1. Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và không quá 48 giờ "
    "trong 01 tuần."
)
P105_2 = (
    "Điều 105. Thời giờ làm việc bình thường\n"
    "2. Người sử dụng lao động có quyền quy định thời giờ làm việc theo ngày hoặc tuần nhưng "
    "phải thông báo cho người lao động biết; trường hợp theo tuần thì thời giờ làm việc bình "
    "thường không quá 10 giờ trong 01 ngày và không quá 48 giờ trong 01 tuần. Nhà nước khuyến "
    "khích người sử dụng lao động thực hiện tuần làm việc 40 giờ đối với người lao động."
)
P20 = (
    "Điều 20. Loại hợp đồng lao động\n"
    "1. Hợp đồng lao động phải được giao kết theo một trong các loại sau đây:\n"
    "a) Hợp đồng lao động không xác định thời hạn là hợp đồng mà trong đó hai bên không xác "
    "định thời hạn, thời điểm chấm dứt hiệu lực của hợp đồng;\n"
    "b) Hợp đồng lao động xác định thời hạn là hợp đồng mà trong đó hai bên xác định thời hạn, "
    "thời điểm chấm dứt hiệu lực của hợp đồng trong thời gian không quá 36 tháng kể từ thời "
    "điểm có hiệu lực của hợp đồng."
)
P98 = (
    "Điều 98. Tiền lương làm thêm giờ, làm việc vào ban đêm\n"
    "1. Người lao động làm thêm giờ được trả lương tính theo đơn giá tiền lương hoặc tiền lương "
    "thực trả theo công việc đang làm như sau:\n"
    "a) Vào ngày thường, ít nhất bằng 150%;\n"
    "b) Vào ngày nghỉ hằng tuần, ít nhất bằng 200%;\n"
    "c) Vào ngày nghỉ lễ, tết, ngày nghỉ có hưởng lương, ít nhất bằng 300% chưa kể tiền lương "
    "ngày lễ, tết, ngày nghỉ có hưởng lương đối với người lao động hưởng lương ngày."
)
P115 = (
    "Điều 115. Nghỉ việc riêng, nghỉ không hưởng lương\n"
    "1. Người lao động được nghỉ việc riêng mà vẫn hưởng nguyên lương và phải thông báo với "
    "người sử dụng lao động trong trường hợp sau đây:\n"
    "a) Kết hôn: nghỉ 03 ngày;\n"
    "b) Con đẻ, con nuôi kết hôn: nghỉ 01 ngày;\n"
    "c) Cha đẻ, mẹ đẻ, cha nuôi, mẹ nuôi; cha đẻ, mẹ đẻ, cha nuôi, mẹ nuôi của vợ hoặc chồng; "
    "vợ hoặc chồng; con đẻ, con nuôi chết: nghỉ 03 ngày."
)
P139 = (
    "Điều 139. Nghỉ thai sản\n"
    "1. Lao động nữ được nghỉ thai sản trước và sau khi sinh con là 06 tháng; thời gian nghỉ "
    "trước khi sinh không quá 02 tháng. Trường hợp lao động nữ sinh đôi trở lên thì tính từ "
    "con thứ 02 trở đi, cứ mỗi con, người mẹ được nghỉ thêm 01 tháng."
)
P21 = (
    "Điều 21. Đối tượng và điều kiện hưởng trợ cấp hưu trí xã hội\n"
    "2. Công dân Việt Nam từ đủ 70 tuổi đến dưới 75 tuổi thuộc hộ nghèo, hộ cận nghèo và đáp "
    "ứng đủ điều kiện quy định tại điểm b và điểm c khoản 1 Điều này thì được hưởng trợ cấp "
    "hưu trí xã hội."
)
P45 = (
    "Điều 45. Trợ cấp ốm đau\n"
    "2. Mức hưởng trợ cấp ốm đau của người lao động quy định tại khoản 1 Điều 43 và Điều 44 "
    "của Luật này bằng 75% tiền lương làm căn cứ đóng bảo hiểm xã hội quy định tại khoản 1 "
    "Điều này."
)

# (premise, claim, should the guard let it through?, what is being tested)
PAIRS = [
    # correct - short clause
    (P35, "Người lao động phải báo trước ít nhất 45 ngày.", True, "verbatim"),
    (P35, "Người lao động hợp đồng không xác định thời hạn phải báo trước 45 ngày khi nghỉ việc.",
     True, "paraphrase"),
    (P105_1, "Thời giờ làm việc bình thường không quá 8 giờ một ngày.", True, "08 -> 8"),
    # correct - one item or sentence of a long clause
    (P20, "Hợp đồng lao động xác định thời hạn được ký tối đa 36 tháng.", True, "long clause"),
    (P105_2, "Nếu quy định theo tuần, thời giờ làm việc bình thường không quá 10 giờ trong "
     "01 ngày.", True, "long clause"),
    (P98, "Làm thêm giờ vào ngày thường được trả lương ít nhất bằng 150%.", True, "long clause"),
    (P115, "Người lao động kết hôn được nghỉ 03 ngày hưởng nguyên lương.", True, "long clause"),
    (P139, "Sinh đôi thì từ con thứ hai, mỗi con người mẹ được nghỉ thêm 01 tháng.", True,
     "long clause"),
    (P21, "Người từ đủ 70 tuổi đến dưới 75 tuổi thuộc hộ nghèo được hưởng trợ cấp hưu trí xã "
     "hội.", True, "long clause"),
    (P45, "Trợ cấp ốm đau bằng 75% tiền lương làm căn cứ đóng bảo hiểm xã hội.", True,
     "long clause"),
    # wrong number
    (P35, "Người lao động phải báo trước ít nhất 90 ngày.", False, "number up"),
    (P35, "Người lao động phải báo trước 30 ngày.", False, "number down"),
    (P105_1, "Thời giờ làm việc bình thường không quá 10 giờ trong 01 ngày.", False, "number"),
    (P105_1, "Thời giờ làm việc bình thường không quá 40 giờ trong 01 tuần.", False, "number"),
    (P98, "Làm thêm giờ vào ngày nghỉ hằng tuần được trả ít nhất bằng 150%.", False,
     "number from other item"),
    (P115, "Con đẻ kết hôn thì người lao động được nghỉ 03 ngày.", False,
     "number from other item"),
    # negation, subject, condition
    (P35, "Người lao động không phải báo trước khi chấm dứt hợp đồng.", False, "negation"),
    (P35, "Người sử dụng lao động phải báo trước ít nhất 45 ngày.", False, "subject swap"),
    (P139, "Lao động nam được nghỉ thai sản 06 tháng.", False, "subject swap"),
    (P35, "Người lao động làm hợp đồng xác định thời hạn phải báo trước ít nhất 45 ngày.",
     False, "condition changed"),
    (P21, "Mọi công dân từ đủ 70 tuổi đến dưới 75 tuổi đều được hưởng trợ cấp hưu trí xã hội.",
     False, "condition dropped"),
    (P35, "Người lao động thử việc phải báo trước ít nhất 45 ngày.", False, "near-miss"),
    (P105_2, "Người sử dụng lao động phải thực hiện tuần làm việc 40 giờ.", False,
     "encouraged -> required"),
    (P45, "Trợ cấp thai sản bằng 75% tiền lương làm căn cứ đóng bảo hiểm xã hội.", False,
     "near-miss"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=settings.nli_model)
    ap.add_argument("--tau", type=float, default=settings.entailment_threshold)
    args = ap.parse_args()

    nli = NLIVerifier(args.model)
    wrong = {"raw": 0, "guard": 0}
    print(f"{'raw':>6} {'guard':>6}  {'expect':6}  {'':5}  {'test':22}  claim")
    for premise, claim, should_pass, note in PAIRS:
        raw = nli.raw_entailment(premise, claim)
        guard = nli.entailment(premise, claim)
        wrong["raw"] += (raw >= args.tau) != should_pass
        wrong["guard"] += (guard >= args.tau) != should_pass
        mark = "ok" if (guard >= args.tau) == should_pass else "WRONG"
        expect = "pass" if should_pass else "block"
        print(f"{raw:6.3f} {guard:6.3f}  {expect:6}  {mark:5}  {note:22}  {claim}")
    print(f"\nwrong at τ={args.tau} ({args.model}), {len(PAIRS)} pairs: "
          f"raw {wrong['raw']}, guard {wrong['guard']}")


if __name__ == "__main__":
    main()
