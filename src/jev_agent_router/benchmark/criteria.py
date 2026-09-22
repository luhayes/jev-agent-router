"""BANKING77 intent descriptions grounded in the pinned training split.

These are benchmark-authored descriptions, not official dataset definitions.
Keep the original category identifiers, including misleading historical names.
See benchmarks/banking77/CRITERIA.md for provenance and review limitations.
"""

CRITERIA_VERSION = "banking77-train-descriptions-v1"

CRITERIA = {
    "Refund_not_showing_up": "A requested or promised merchant refund has not appeared in the account.",
    "activate_my_card": "How to activate a new card, or trouble completing card activation.",
    "age_limit": "Minimum age, age restrictions, or opening an account for a child.",
    "apple_pay_or_google_pay": "Adding money using Apple Pay or Google Pay, including wallet top-up problems.",
    "atm_support": "Which ATMs accept the card, and where to find a compatible ATM.",
    "automatic_top_up": "Setting up, finding, changing, or understanding automatic balance top-ups.",
    "balance_not_updated_after_bank_transfer": (
        "An incoming bank transfer was sent but has not appeared in this account's balance."
    ),
    "balance_not_updated_after_cheque_or_cash_deposit": (
        "A cash or cheque deposit has been made but is missing from the account balance."
    ),
    "beneficiary_not_allowed": (
        "A transfer to an account or beneficiary is not permitted or possible, including unsupported recipients."
    ),
    "cancel_transfer": "Cancel, reverse, or stop a money transfer, including one sent to the wrong account.",
    "card_about_to_expire": "Renewing or replacing an expiring or expired card, including while abroad.",
    "card_acceptance": "Where the card can be used for purchases: merchants, countries, or types of business.",
    "card_arrival": "An ordered card has not arrived; checking its delivery status, tracking, or a delay.",
    "card_delivery_estimate": "Expected delivery time for a card, including delivery to a particular country.",
    "card_linking": "Linking a card to the app/account, or restoring a previously removed or found card.",
    "card_not_working": "A physical card is broken or generally not working; diagnosing or replacing it.",
    "card_payment_fee_charged": "A fee or surcharge for making a card payment, or questions about purchase fees.",
    "card_payment_not_recognised": "An unfamiliar or unauthorized card purchase shown in the account.",
    "card_payment_wrong_exchange_rate": "An incorrect or unexpected exchange rate applied to a card purchase.",
    "card_swallowed": "An ATM retained or swallowed the card and will not return it.",
    "cash_withdrawal_charge": "A fee charged for withdrawing cash at an ATM, or ATM withdrawal fees.",
    "cash_withdrawal_not_recognised": "An ATM cash withdrawal on the account that the customer did not make.",
    "change_pin": "Setting or changing the card PIN to a new number; how and where to do it.",
    "compromised_card": "Suspected card compromise, fraud, or someone else using the card; securing the card.",
    "contactless_not_working": "Contactless/tap payments are not working or are being refused.",
    "country_support": "Countries of residence supported for opening an account or obtaining the service.",
    "declined_card_payment": "A card payment for a purchase was declined or rejected.",
    "declined_cash_withdrawal": "An ATM cash withdrawal was declined or refused; no cash could be withdrawn.",
    "declined_transfer": "A money transfer is reported as declined or rejected; asking why.",
    "direct_debit_payment_not_recognised": "An unfamiliar or unauthorized direct debit; disputing that debit.",
    "disposable_card_limits": "Limits or restrictions on disposable virtual cards, including how many are allowed.",
    "edit_personal_details": "Changing personal account details such as name, address, phone number, or email.",
    "exchange_charge": "Fees or charges for exchanging one currency into another.",
    "exchange_rate": "Which exchange rate is used, how it is determined, or weekday/weekend rates.",
    "exchange_via_app": "How to exchange or convert currencies within the app.",
    "extra_charge_on_statement": "An unexpected small extra charge, often one pound, euro, or dollar.",
    "failed_transfer": "A money transfer failed or produced an error; troubleshooting an unsuccessful transfer.",
    "fiat_currency_support": "Which currencies can be held or exchanged in the account.",
    "get_disposable_virtual_card": "Getting a disposable virtual card, its purpose, or how it works.",
    "get_physical_card": (
        "Finding, viewing, obtaining, or receiving the card PIN, including a PIN that has not arrived."
    ),
    "getting_spare_card": "Ordering an additional or spare card, including an extra card for a family member.",
    "getting_virtual_card": "Obtaining or accessing a virtual card, or a virtual card that has not appeared.",
    "lost_or_stolen_card": "A physical card is lost or stolen; reporting, freezing, or replacing it.",
    "lost_or_stolen_phone": "A phone with account/app access is lost or stolen; protecting or recovering access.",
    "order_physical_card": "Ordering a physical card: how to request it, its cost, or delivery destinations.",
    "passcode_forgotten": "A forgotten or nonworking app login passcode/password; recovering account access.",
    "pending_card_payment": "A card purchase is still pending or awaiting completion.",
    "pending_cash_withdrawal": "An ATM cash withdrawal is shown as pending, including one that dispensed no cash.",
    "pending_top_up": "An account top-up is pending, processing, or taking time to appear.",
    "pending_transfer": "A submitted money transfer is still pending or processing; when it will complete.",
    "pin_blocked": "A card PIN is blocked after incorrect attempts; unblocking or resetting the attempt limit.",
    "receiving_money": "Receiving salary, payments, or money from other people into the account.",
    "request_refund": "How to request a refund or reverse a purchase; whether a purchase is refundable.",
    "reverted_card_payment?": "A card payment was reversed or reverted and the money returned to the account.",
    "supported_cards_and_currencies": "Which external cards, card networks, or currencies are accepted for top-ups.",
    "terminate_account": "Closing or deleting the account and ending the service.",
    "top_up_by_bank_transfer_charge": "Fees for receiving money or topping up via bank transfer, including SEPA.",
    "top_up_by_card_charge": "Fees for adding money by card, including cards issued in other countries.",
    "top_up_by_cash_or_cheque": "Whether and how to add money using cash or a cheque.",
    "top_up_failed": "A top-up failed, was declined, or could not be completed.",
    "top_up_limits": "Minimum/maximum top-up amounts, frequency limits, or other top-up allowances.",
    "top_up_reverted": "A top-up was reversed, reverted, or cancelled after being attempted or credited.",
    "topping_up_by_card": "How to add money using a credit/debit card, including another person's card.",
    "transaction_charged_twice": "The same purchase or transaction was charged more than once.",
    "transfer_fee_charged": "A fee deducted or charged for sending a money transfer, including international fees.",
    "transfer_into_account": "How to fund this account by transferring money from another bank account.",
    "transfer_not_received_by_recipient": "Money was sent but the intended recipient has not received the transfer.",
    "transfer_timing": "Expected bank-transfer duration, including domestic or international processing times.",
    "unable_to_verify_identity": "Identity verification is failing, rejected, or cannot be completed.",
    "verify_my_identity": "How to verify identity and which documents or steps are required.",
    "verify_source_of_funds": "Explaining, checking, or verifying where account funds come from.",
    "verify_top_up": "Verifying a top-up or top-up card, including finding the verification code.",
    "virtual_card_not_working": "A virtual or disposable virtual card does not work or its payment is rejected.",
    "visa_or_mastercard": "Whether cards are Visa or Mastercard, or choosing a preferred card network.",
    "why_verify_identity": "Why identity verification is required, or whether it can be avoided.",
    "wrong_amount_of_cash_received": "An ATM dispensed a different amount of cash than requested or debited.",
    "wrong_exchange_rate_for_cash_withdrawal": "An incorrect or unexpected exchange rate on an ATM cash withdrawal.",
}
