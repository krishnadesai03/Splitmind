from ..models.db import Expense, Participant, Item, Assignment
from ..models.schemas import PersonSplit


def calculate_splits(
    expense: Expense,
    participants: list[Participant],
    items: list[Item],
) -> tuple[list[PersonSplit], list[str]]:
    """
    Returns (splits, unassigned_item_names).
    Unassigned items are listed separately so the UI can warn the user.
    """
    if not participants:
        return [], [item.name for item in items]

    # Build {participant_id: subtotal_share}
    person_subtotals: dict[str, float] = {p.id: 0.0 for p in participants}
    assigned_item_ids: set[str] = set()

    for item in items:
        if not item.assignments:
            continue
        assigned_item_ids.add(item.id)
        share_each = round(item.price / len(item.assignments), 4)
        for assignment in item.assignments:
            person_subtotals[assignment.participant_id] = (
                person_subtotals.get(assignment.participant_id, 0.0) + share_each
            )

    group_subtotal = sum(person_subtotals.values())

    splits: list[PersonSplit] = []
    for p in participants:
        ps = round(person_subtotals[p.id], 2)

        if expense.tax_split == "proportional" and group_subtotal > 0:
            proportion = person_subtotals[p.id] / group_subtotal
            ptax = round(expense.tax * proportion, 2)
            ptip = round(expense.tip * proportion, 2)
        else:
            ptax = round(expense.tax / len(participants), 2)
            ptip = round(expense.tip / len(participants), 2)

        splits.append(PersonSplit(
            participant_id=p.id,
            name=p.name,
            subtotal=ps,
            tax=ptax,
            tip=ptip,
            total=round(ps + ptax + ptip, 2),
        ))

    # Absorb rounding discrepancy into the first person
    if splits:
        computed_total = sum(s.total for s in splits)
        discrepancy = round(expense.total - computed_total, 2)
        if discrepancy != 0:
            splits[0] = splits[0].model_copy(
                update={"total": round(splits[0].total + discrepancy, 2)}
            )

    unassigned = [item.name for item in items if item.id not in assigned_item_ids]
    return splits, unassigned
