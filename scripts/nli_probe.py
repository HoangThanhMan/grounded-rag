"""Day 9 of the roadmap: does the NLI model catch Vietnamese claims that keep
most of the wording but change a number, the subject or a condition?

    python scripts/nli_probe.py          # needs the `models` extra

Eleven pairs is a first look, not a verdict. Extend PAIRS to 20+ - with more
subject swaps and near-misses, the cases this model got wrong - before
trusting the guard, and before calibrating τ.
"""

from grounded_rag.config import settings
from grounded_rag.guard.nli_verifier import NLIVerifier

P35 = (
    "Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động của người lao động\n"
    "1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động nhưng phải báo trước "
    "ít nhất 45 ngày nếu làm việc theo hợp đồng lao động không xác định thời hạn."
)
P105 = (
    "Điều 105. Thời giờ làm việc bình thường\n"
    "1. Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và không quá 48 giờ "
    "trong 01 tuần."
)

# (premise, claim, should the guard let it through?, what is being tested)
PAIRS = [
    (P35, "Người lao động phải báo trước ít nhất 45 ngày.", True, "verbatim"),
    (P35, "Người lao động hợp đồng không xác định thời hạn phải báo trước 45 ngày khi nghỉ việc.",
     True, "paraphrase"),
    (P105, "Thời giờ làm việc bình thường không quá 8 giờ một ngày.", True, "08 -> 8"),
    (P35, "Người lao động phải báo trước ít nhất 90 ngày.", False, "number up"),
    (P35, "Người lao động phải báo trước 30 ngày.", False, "number down"),
    (P105, "Thời giờ làm việc bình thường không quá 10 giờ trong 01 ngày.", False, "number"),
    (P105, "Thời giờ làm việc bình thường không quá 40 giờ trong 01 tuần.", False, "number"),
    (P35, "Người lao động không phải báo trước khi chấm dứt hợp đồng.", False, "negation"),
    (P35, "Người sử dụng lao động phải báo trước ít nhất 45 ngày.", False, "subject swap"),
    (P35, "Người lao động làm hợp đồng xác định thời hạn phải báo trước ít nhất 45 ngày.",
     False, "condition changed"),
    (P35, "Người lao động thử việc phải báo trước ít nhất 45 ngày.", False, "near-miss"),
]


def main() -> None:
    nli = NLIVerifier()
    tau = settings.entailment_threshold
    wrong = 0
    for premise, claim, should_pass, note in PAIRS:
        score = nli.entailment(premise, claim)
        passed = score >= tau
        wrong += passed != should_pass
        mark = "ok" if passed == should_pass else "WRONG"
        print(f"{score:6.3f}  {'pass' if passed else 'block':5}  {mark:5}  {note:17}  {claim}")
    print(f"\n{wrong}/{len(PAIRS)} wrong at τ={tau} ({settings.nli_model})")


if __name__ == "__main__":
    main()
