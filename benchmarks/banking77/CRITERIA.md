# BANKING77 category descriptions

Version: `banking77-train-descriptions-v1`.

The complete English definitions live in
[`criteria.py`](../../src/jev_agent_router/benchmark/criteria.py). These are
benchmark-authored interpretations, not official definitions or relabeled data.
All 77 original category keys, including capitalization and punctuation, remain
unchanged. Both Jev and the LLM receive the same description dictionary.

## Source and review

Source: PolyAI's
[`banking_data/train.csv`](https://github.com/PolyAI-LDN/task-specific-datasets/blob/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/train.csv)
at revision `57ec275d8078af65b7731c2a98be812d844a6d6b`.
Training-file SHA-256:
`b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`.
The data remains CC-BY-4.0; see the [benchmark attribution](README.md#attribution).

For this revision, six training examples per category were inspected using
`random.Random(42).sample(category_rows, 6)`, preserving CSV order within each
category and resetting the seed for each category. This covers 462 examples,
not an exhaustive annotation audit. Additional training examples for PIN and
physical-card categories were checked. Descriptions summarize the intended
task; ambiguous or inconsistent source examples are not silently corrected.

The review was prompted by errors in the first standard evaluation. The revised
wording was grounded in training examples, without selecting descriptions by
test accuracy. Nevertheless, the original test subset has already been inspected:
reruns on it must be reported as revised evaluations, not untouched held-out
validation. No performance improvement is established until new calls are made.

## Important distinctions

| Original category | Meaning used in this benchmark |
|---|---|
| `get_physical_card` | Find, view, obtain, or receive the card PIN. The historical category name is misleading. |
| `order_physical_card` | Request an actual physical card, its cost, or delivery destinations. |
| `change_pin` | Set or change the card PIN to a new number. |
| `pin_blocked` | Unblock a PIN after incorrect attempts. |
| `passcode_forgotten` | Recover an app login passcode/password. |
| `card_linking` | Link or restore a card in the app, including a found card. |
| `card_arrival` | Track an ordered card or investigate a delivery delay. |
| `card_delivery_estimate` | Ask about expected delivery duration. |
| `balance_not_updated_after_bank_transfer` | Incoming transfer missing from this account. |
| `transfer_not_received_by_recipient` | Sent transfer missing at its intended recipient. |
| `pending_transfer` | Submitted transfer still pending or processing. |
| `transfer_timing` | Expected transfer duration. |
| `supported_cards_and_currencies` | External cards/currencies accepted for top-ups. |
| `fiat_currency_support` | Currencies that can be held or exchanged. |

Some distinctions overlap in the source examples, especially failed, declined,
and disallowed transfers. These definitions do not imply perfectly separable
classes. Original labels remain the scoring reference.

## Reproduction and migration

`prepare` writes the full definitions and `criteria_metadata` to the manifest.
The version, provenance, and actual definition text are included in the existing
dataset hash. A wording or version change therefore invalidates resume identity
and frozen-policy compatibility. Reports display the recorded version, never
the version from the currently installed code. Older manifests are shown as
`unversioned` and can still be analyzed with their original definitions.

Start a new preparation and new smoke/dev/test/live collections. Do not edit
an old manifest, reuse an old threshold policy, or relabel old predictions as
results from these descriptions. A fresh GitHub Actions **Run workflow** on
`main` prepares the revised descriptions automatically; rerunning an old job
uses that job's original commit. Threshold selection rules are unchanged.

Descriptions are longer than the previous underscore-to-space labels and can
increase input tokens and cost. Compare strategies within the new run using
their recorded usage, and identify the prompt-version change when comparing
against earlier results. Offline replay cannot measure the effect of a changed
prompt on model predictions.
