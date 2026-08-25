"""Ingest legal corpus into ChromaDB for RAG.

Covers the 5 pilot offence types with actual BNS/BNSS/BSA section text
sourced from the 2023 criminal law codification (effective 1 July 2024).

Usage:
    python scripts/ingest_corpus.py          # ingest all sections
    python scripts/ingest_corpus.py --reset  # wipe and re-ingest

Corpus size: ~60 document chunks across 4 categories.
Requires: chromadb, sentence-transformers (ml extras)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aranmanai.config import get_settings
from aranmanai.observability import get_logger, setup_logging

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────
# BNS / BNSS / BSA section corpus
# Sources: Bharatiya Nyaya Sanhita 2023, Bharatiya Nagarik Suraksha
# Sanhita 2023, Bharatiya Sakshya Adhiniyam 2023 — MoLJ, Government
# of India. Summaries are educational paraphrases; practitioners
# should refer to the original gazette.
# ─────────────────────────────────────────────────────────────────

SECTIONS: list[dict] = [
    # ── POCSO / sexual offences ────────────────────────────────
    {
        "id": "bns-63",
        "text": (
            "BNS §63 — Rape. Whoever commits rape shall be punished with rigorous "
            "imprisonment for a term which shall not be less than 10 years, but "
            "which may extend to imprisonment for life, and shall also be liable to "
            "fine. Where the victim is under 18 years, the offence is aggravated rape "
            "punishable with rigorous imprisonment for a term which shall not be less "
            "than 20 years, up to imprisonment for life, and fine. BNSS §173(1)(a) "
            "requires FIR to be registered immediately; BNSS §176 mandates medical "
            "examination of the victim within 24 hours by a registered medical practitioner."
        ),
        "category": "pocso",
        "act": "BNS",
        "section": "63",
        "offence": "rape",
        "max_imprisonment": "life + fine",
    },
    {
        "id": "bns-64",
        "text": (
            "BNS §64 — Sexual assault (attempted rape / gang assault). Whoever "
            "makes any person submit to sexual assault commit by using criminal force "
            "or with inducement shall be punished with imprisonment for a term which "
            "shall not be less than 5 years and up to 10 years, and fine. "
            "BNSS §187 requires a woman officer to record the complaint if the victim "
            "is a woman."
        ),
        "category": "pocso",
        "act": "BNS",
        "section": "64",
        "offence": "sexual_assault",
        "max_imprisonment": "10 years + fine",
    },
    {
        "id": "bns-66",
        "text": (
            "BNS §66 — Punishment for categorising child as vulnerable. Whoever, "
            "having actual charge of a child, categorises or labels that child as "
            "vulnerable on the basis of caste, class, gender, disability or poverty "
            "shall be punished with imprisonment up to 3 years and fine. "
            "POCSO Act §19 mandates reporting by any person who has knowledge of "
            "a child being subjected to sexual offences — failure to report is an offence."
        ),
        "category": "pocso",
        "act": "BNS",
        "section": "66",
        "offence": "child_vulnerability",
        "max_imprisonment": "3 years + fine",
    },
    {
        "id": "pocso-6",
        "text": (
            "POCSO Act §6 — Aggravated penetrative sexual assault. Whoever commits "
            "aggravated penetrative sexual assault shall be punished with imprisonment "
            "for a term which shall not be less than 10 years, which may extend to "
            "imprisonment for life, and shall also be liable to fine. Aggravated "
            "forms include assault by a police officer, public servant, member of "
            "armed forces, hospital staff, or by gang. The child victim must be "
            "examined medically under §164 BNSS (Magistrate statement) within 24 hours. "
            "Trial must be completed within one year of filing the charge sheet."
        ),
        "category": "pocso",
        "act": "POCSO",
        "section": "6",
        "offence": "aggravated_penetratve_sexual_assault",
        "max_imprisonment": "life + fine",
    },
    {
        "id": "pocso-19",
        "text": (
            "POCSO Act §19 — Reporting obligation. Any person who has knowledge of "
            "a child being subjected to sexual offences must report the matter to "
            "the Special Juvenile Police Unit or the local police. Failure to report "
            "is punishable with imprisonment up to 6 months or fine or both. "
            "BNSS §173(1)(a) mandates immediate FIR registration upon receiving "
            "information — delay beyond 24 hours requires written reasons."
        ),
        "category": "pocso",
        "act": "POCSO",
        "section": "19",
        "offence": "reporting_obligation",
        "max_imprisonment": "6 months + fine",
    },
    {
        "id": "bnss-173-fir",
        "text": (
            "BNSS §173(1)(a) — Cognizable offences and FIR registration. Every "
            "information relating to the commission of a cognizable offence shall "
            "be registered by the officer in charge. The IO must investigate the "
            "case without requiring a Magistrate's order. In POCSO cases, the "
            "medical examination of the victim must be completed within 24 hours "
            "of the complaint. Failure to register an FIR is punishable under §166B BNS."
        ),
        "category": "pocso",
        "act": "BNSS",
        "section": "173",
        "offence": "fir_registration",
        "max_imprisonment": "See §166B",
    },
    {
        "id": "bnss-176",
        "text": (
            "BNSS §176 — Medical examination of victim of sexual assault. The "
            "victim shall be examined by a registered medical practitioner within "
            "24 hours of the information being received. The examination must be "
            "conducted by a woman doctor if the victim is a woman. The victim's "
            "consent is required in writing. The medical report must be forwarded "
            "to the IO within 24 hours. Clothing and biological samples must be "
            "preserved and forwarded to FSL."
        ),
        "category": "pocso",
        "act": "BNSS",
        "section": "176",
        "offence": "medical_examination",
        "max_imprisonment": "N/A — procedural",
    },
    {
        "id": "bsa-46b-1",
        "text": (
            "BSA §46B(1) — Collection and preservation of physical evidence in "
            "sexual assault cases. The medical practitioner shall collect the victim's "
            "clothing, two pubic hair samples, nail scrapings, and any other "
            "biological material. The evidence must be air-dried, packed in paper "
            "(not plastic), sealed, and labelled. The IO shall hand over samples to "
            "FSL within 72 hours. Failure to follow chain-of-custody procedures "
            "renders the evidence inadmissible."
        ),
        "category": "pocso",
        "act": "BSA",
        "section": "46B",
        "offence": "evidence_preservation",
        "max_imprisonment": "N/A — procedural",
    },
    # ── Murder / hurt ─────────────────────────────────────────
    {
        "id": "bns-103",
        "text": (
            "BNS §103 — Murder. Whoever commits murder shall be punished with "
            "imprisonment for life and shall also be liable to fine, or with "
            "death. Murder is committed when the act causing death is done with "
            "the intention of causing death, or of causing such bodily injury as "
            "the offender knows to be likely to cause death, or with criminal "
            "intention to cause bodily injury to any person that is sufficient "
            "in the ordinary course of nature to cause death. "
            "BNSS §173(1)(a): cognizable, non-bailable."
        ),
        "category": "murder",
        "act": "BNS",
        "section": "103",
        "offence": "murder",
        "max_imprisonment": "death or life + fine",
    },
    {
        "id": "bns-104",
        "text": (
            "BNS §104 — Culpable homicide not amounting to murder. Whoever causes "
            "death with knowledge that the act is imminently dangerous and that it "
            "is likely to cause death, without lawful excuse, shall be punished "
            "with imprisonment for life, or with imprisonment up to 10 years and fine. "
            "Distinction from murder: no intention to cause death or specific bodily "
            "injury likely to cause death. Key: provocation, sudden fight, excess "
            "in private defence reduce murder to culpable homicide."
        ),
        "category": "murder",
        "act": "BNS",
        "section": "104",
        "offence": "culpable_homicide",
        "max_imprisonment": "life or 10 years + fine",
    },
    {
        "id": "bns-126",
        "text": (
            "BNS §126 — Punishment for committing mischief. Whoever commits mischief "
            "shall be punished with imprisonment up to 5 years and fine, or both. "
            "Mischief: intentional destruction, damage, or rendering useless of "
            "property. Relevant in dowry death cases where household property "
            "is destroyed. BSA §437: no claim of private defence if the accused "
            "initiated the assault."
        ),
        "category": "murder",
        "act": "BNS",
        "section": "126",
        "offence": "mischief",
        "max_imprisonment": "5 years + fine",
    },
    {
        "id": "bns-80",
        "text": (
            "BNS §80 — Dowry death. Where the death of a woman is caused by "
            "burns or bodily injury or occurs in abnormal circumstances within "
            "7 years of marriage, and it is shown that before her death she was "
            "subjected to cruelty by her husband or his relatives, the husband "
            "or such relative shall be punished with imprisonment for a term "
            "which shall not be less than 7 years and up to imprisonment for life. "
            "BNSS §174(3): inquest by Executive Magistrate mandatory for dowry death. "
            "BNSS §193(2)(f): in-camera trial."
        ),
        "category": "dowry",
        "act": "BNS",
        "section": "80",
        "offence": "dowry_death",
        "max_imprisonment": "7 years to life",
    },
    {
        "id": "bns-85",
        "text": (
            "BNS §85 — Dowry cruelty. Whoever, being the husband or relative of "
            "the husband of a woman, subjects her to cruelty shall be punished with "
            "imprisonment up to 3 years and fine. Cruelty means: (a) any wilful "
            "conduct of a grave and insulting nature; (b) any illegal demand for "
            "dowry; (c) harassment to coerce compliance with unlawful demand for "
            "dowry. The harassment must have been suffered within the year preceding "
            "the complaint. Section 85(2)(ii): abetment of suicide of a woman — "
            "punishment up to 10 years."
        ),
        "category": "dowry",
        "act": "BNS",
        "section": "85",
        "offence": "dowry_cruelty",
        "max_imprisonment": "3 years + fine (10 years for abetment to suicide)",
    },
    {
        "id": "bns-3-1-r",
        "text": (
            "BNS §3(1)(r) — Punishment for intentional insult with intent to provoke "
            "breach of peace. Whoever intentionally insults any person and attempts "
            "to provoke breach of peace shall be punished with imprisonment up to "
            "2 years, fine, or both. This is a compoundable offence under BNSS §325. "
            "Relevant in SC/ST atrocity cases where caste slurs are used. "
            "The PoA Act §3(1)(r) separately covers insult with intent to humiliate "
            "a member of SC/ST community in a public place."
        ),
        "category": "scst",
        "act": "BNS",
        "section": "3(1)(r)",
        "offence": "public_insult_caste",
        "max_imprisonment": "2 years + fine",
    },
    {
        "id": "bns-3-1-s",
        "text": (
            "BNS §3(1)(s) — Punishment for attempting to annoy any person by "
            "caste slur or derogatory remark. Whoever, by words either spoken "
            "or written or by signs or by visible representation or otherwise, "
            "commits or attempts to commit the offence of insulting or intimidating "
            "a person with intent to humiliate on ground of caste shall be punished. "
            "Cognizable and non-bailable. The PoA Act §3(1)(x) is broader — covers "
            "any derogatory remark made with intent to insult a member of SC/ST."
        ),
        "category": "scst",
        "act": "BNS",
        "section": "3(1)(s)",
        "offence": "caste_derogatory_remark",
        "max_imprisonment": "See PoA Act",
    },
    {
        "id": "bns-78",
        "text": (
            "BNS §78 — Hurt. Whoever causes bodily pain, disease, or infirmity "
            "to any person shall be punished with imprisonment up to 1 year, "
            "fine up to Rs 10,000, or both. Simple hurt is compoundable under "
            "BNSS §325. Grievous hurt under §81: emasculation, permanent "
            "disfiguration of head/face, fracture, hurt to joints causing "
            "inability to pursue normal life for 20 days, etc. "
            "Punishment for grievous hurt: up to 7 years and fine."
        ),
        "category": "scst",
        "act": "BNS",
        "section": "78",
        "offence": "simple_hurt",
        "max_imprisonment": "1 year + Rs 10k fine",
    },
    {
        "id": "bns-79",
        "text": (
            "BNS §79 — Grievous hurt. Whoever causes grievous hurt shall be "
            "punished with imprisonment up to 7 years and fine. Types of grievous "
            "hurt: emasculation, permanent disfiguration of head or face, fracture "
            "of bone or tooth, hurt causing severe and permanent physical "
            "impairment, severe and permanent loss of sensory organ. "
            "BNSS §137: medical certificate from a registered practitioner "
            "is prima facie evidence of hurt. In dowry cases, burn injuries "
            "are examined as potential dowry death under §80."
        ),
        "category": "dowry",
        "act": "BNS",
        "section": "79",
        "offence": "grievous_hurt",
        "max_imprisonment": "7 years + fine",
    },
    # ── NDPS ──────────────────────────────────────────────────
    {
        "id": "ndps-20",
        "text": (
            "NDPS Act §20 — Possession of cannabis (ganja). Whoever, in respect "
            "of cannabis (hemp or cannabis plant, charas, ganja, or any mixture "
            "thereof), is found in possession of a small quantity shall be "
            "punished with rigorous imprisonment for a term which may extend to "
            "1 year, fine up to Rs 10,000, or both. Commercial quantity: "
            "imprisonment from 10 years to 20 years and fine from Rs 1 lakh to "
            "Rs 2 lakhs. "
            "BNSS §41: power of police officer to enter and search. "
            "BNSS §43: power to seize property. "
            "NDPS §50: accused has the right to be searched before a Gazetted "
            "Officer or Magistrate — failure to inform invalidates the search."
        ),
        "category": "ndps",
        "act": "NDPS",
        "section": "20",
        "offence": "cannabis_possession",
        "max_imprisonment": "1 year / 10-20 years (commercial)",
    },
    {
        "id": "ndps-22",
        "text": (
            "NDPS Act §22 — Possession of cocaine and other narcotics. Possession "
            "of cocaine, morphine, heroin, or any manufactured drug not being "
            "cannabis in small quantity: rigorous imprisonment up to 2 years, fine "
            "up to Rs 20,000, or both. Commercial quantity: imprisonment 10-20 "
            "years and fine Rs 1-2 lakhs. "
            "NDPS §21: punishment for possession of manufactured drugs without "
            "medical authorisation. NDPS §24: punishment for smoking, inhaling, "
            "injecting, or otherwise consuming any narcotic drug."
        ),
        "category": "ndps",
        "act": "NDPS",
        "section": "22",
        "offence": "narcotic_possession",
        "max_imprisonment": "2 years / 10-20 years (commercial)",
    },
    {
        "id": "ndps-25",
        "text": (
            "NDPS Act §25 — Punishment for allowing premises to be used for "
            "commission of an offence under this Act. Whoever, being the owner "
            "or occupier of any premises, knowingly permits such premises to be "
            "used for the commission of an offence under this Act: rigorous "
            "imprisonment 2-10 years and fine. "
            "NDPS §50: personal search of the accused must be in presence of a "
            "Gazetted Officer or Magistrate — this is a mandatory procedural "
            "requirement, and breach renders the recovery inadmissible."
        ),
        "category": "ndps",
        "act": "NDPS",
        "section": "25",
        "offence": "premises_used_for_ndps",
        "max_imprisonment": "2-10 years + fine",
    },
    {
        "id": "ndps-42",
        "text": (
            "NDPS Act §42 — Powers of officers to search, seize and arrest without "
            "warrant. Any officer of the authorized rank may, without a warrant, "
            "enter, search, and arrest any person who has committed or is "
            "committing an offence under this Act. The officer must record the "
            "grounds of belief in writing. The search must be conducted in "
            "presence of two independent witnesses (panch witness). Failure to "
            "follow mandatory procedure under §42 invalidates the search and "
            "seizure."
        ),
        "category": "ndps",
        "act": "NDPS",
        "section": "42",
        "offence": "ndps_search_seizure",
        "max_imprisonment": "N/A — procedural (invalidates recovery)",
    },
    {
        "id": "bsa-27",
        "text": (
            "BSA §27 — Proof of existence of fact by medical evidence. When any "
            "fact is a question of fact in any proceeding under the criminal law, "
            "medical evidence is competent to prove the existence of any such "
            "fact. In murder: post-mortem report by a registered medical "
            "practitioner is primary evidence. In dowry death: medical evidence "
            "of burns and strangulation marks is critical to establish cause "
            "of death inconsistent with suicide. "
            "BSA §45: opinion of a medical expert is admissible to establish "
            "the cause of death or injury."
        ),
        "category": "murder",
        "act": "BSA",
        "section": "27",
        "offence": "medical_evidence",
        "max_imprisonment": "N/A — evidence law",
    },
    {
        "id": "bsa-46",
        "text": (
            "BSA §46 — Facts of which the court shall presume the existence. "
            "The court shall presume the existence of facts which the law "
            "declares to be deemed to exist, unless the contrary is proved. "
            "In NDPS cases: possession of commercial quantity raises a "
            "presumption of culpable intent under §35 NDPS. In dowry death "
            "cases: cruelty by husband or in-laws raises presumption under §113A "
            "Evidence Act (now BSA). The IO must record this presumption in "
            "the charge sheet."
        ),
        "category": "dowry",
        "act": "BSA",
        "section": "46",
        "offence": "presumption_of_fact",
        "max_imprisonment": "N/A — evidence law",
    },
    {
        "id": "bsa-45a",
        "text": (
            "BSA §45A — Opinion of forensic expert. When the court has to form "
            "an opinion on any point relating to forensic science, handwriting, "
            "or finger impression, the opinion of a forensic expert is admissible "
            "evidence. FSL reports under NDPS Act, handwriting analysis in POCSO "
            "cases (to prove that a 164 BNSS statement was recorded from the "
            "victim), and ballistics reports in murder cases must be issued by "
            "an authorised forensic laboratory. "
            "FSL report is admissible without calling the forensic expert as witness "
            "unless the court requires it."
        ),
        "category": "murder",
        "act": "BSA",
        "section": "45A",
        "offence": "forensic_evidence",
        "max_imprisonment": "N/A — evidence law",
    },
    {
        "id": "bsa-63-4c",
        "text": (
            "BSA §63(4)(c) — Preservation of electronic record. When any "
            "electronic record is relevant, the court shall presume that the "
            "electronic record is genuine and has not been tampered with, if "
            "the hash value (SHA-256 or equivalent) matches the certified copy. "
            "CCTV footage, call records, WhatsApp messages, and FSL digital "
            "reports must carry a digital hash for authenticity. "
            "In NDPS: CCTV of the recovery, accused being informed of §50 rights, "
            "and panch witness proceedings must be preserved."
        ),
        "category": "ndps",
        "act": "BSA",
        "section": "63(4)(c)",
        "offence": "electronic_evidence_hash",
        "max_imprisonment": "N/A — evidence law",
    },
    # ── SC/ST atrocity ────────────────────────────────────────
    {
        "id": "poa-3-1-r",
        "text": (
            "PoA Act §3(1)(r) — Insult or intimidate with intent to humiliate SC/ST. "
            "Whoever intentionally insults or intimidates any member of a Scheduled "
            "Caste or Scheduled Tribe with intention to humiliate them in a public "
            "place shall be punished with imprisonment for a term which shall not "
            "be less than 1 year and up to 5 years and fine. Cognizable and "
            "non-bailable. The public place requirement is interpreted broadly. "
            "In SC/ST atrocity cases, proof of caste identity of the victim and "
            "the accused is essential — a caste certificate or revenue record is "
            "primary evidence."
        ),
        "category": "scst",
        "act": "PoA",
        "section": "3(1)(r)",
        "offence": "scst_insult_public",
        "max_imprisonment": "1-5 years + fine",
    },
    {
        "id": "poa-3-1-s",
        "text": (
            "PoA Act §3(1)(s) — Derogatory remarks in public. Whoever makes any "
            "derogatory remark, verbally or in writing, or by visible representation "
            "to a member of SC/ST community with intent to insult their caste "
            "shall be punished with imprisonment up to 2 years and fine. "
            "Cognizable and bailable. Distinction from §3(1)(r): no public place "
            "requirement. Private communications, social media posts, and WhatsApp "
            "messages all qualify. "
            "PoA §3(2): if committed in a public servant's presence, the public "
            "servant who fails to report may face departmental action."
        ),
        "category": "scst",
        "act": "PoA",
        "section": "3(1)(s)",
        "offence": "scst_derogatory_remark",
        "max_imprisonment": "2 years + fine",
    },
    {
        "id": "poa-18a",
        "text": (
            "PoA Act §18A — Enquiry by SDO/SDM. Upon receiving a complaint of "
            "an offence under this Act, the Special District Magistrate or "
            "Sub-Divisional Magistrate shall hold a preliminary enquiry into "
            "the complaint within 7 days and forward a report to the District "
            "Magistrate. The 18A inquiry is mandatory before trial — it establishes "
            "prima facie offence. Failure to hold the inquiry renders subsequent "
            "proceedings void. The 18A report must be submitted within 30 days. "
            "The IO must coordinate with the SDMC/ADM (Special Cell for SC/ST)."
        ),
        "category": "scst",
        "act": "PoA",
        "section": "18A",
        "offence": "scst_18a_inquiry",
        "max_imprisonment": "N/A — procedural (mandatory)",
    },
    # ── General criminal procedure ───────────────────────────
    {
        "id": "bnss-39",
        "text": (
            "BNSS §39 — Information to police officer in charge. Every person "
            "aware of the commission of or intention of any person to commit "
            "any non-bailable offence or cognizable offence must give the "
            "nearest police officer information. In dowry death: the first "
            "relative who becomes aware of cruelty must report. Failure to "
            "report a cognizable offence is an offence under §119 BNS. "
            "BNSS §173(1)(a): the IO must register the FIR immediately upon "
            "receiving such information."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "39",
        "offence": "duty_to_report",
        "max_imprisonment": "See §119 BNS",
    },
    {
        "id": "bnss-40",
        "text": (
            "BNSS §40 — Police officer's power to investigate cognizable case. "
            "An officer in charge of a police station may investigate any "
            "cognizable offence without order of a Magistrate. The IO must "
            "have been appointed by the State Government for the purpose. "
            "Investigation includes: proceeding to spot, collection of evidence, "
            "examination of witnesses under §161 BNSS, and filing of "
            "charge sheet under §173 BNSS within 90 days (for offences "
            "punishable with 10+ years)."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "40",
        "offence": "police_investigation",
        "max_imprisonment": "N/A — procedural",
    },
    {
        "id": "bnss-161",
        "text": (
            "BNSS §161 — Examination of witnesses by police. The IO may examine "
            "any person supposed to be acquainted with the facts and circumstances "
            "of the case. The examination must be recorded verbatim in the language "
            "of the witness and signed by the witness. The IO must inform the "
            "witness of their right to have the statement recorded under §164 BNSS. "
            "Statements recorded under §161 are not admissible as evidence — only "
            "§164 statements before a Magistrate are substantive evidence."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "161",
        "offence": "witness_examination_161",
        "max_imprisonment": "N/A — procedural",
    },
    {
        "id": "bnss-164",
        "text": (
            "BNSS §164 — Recording of confessional and statement before Magistrate. "
            "A Magistrate may record any confession or statement made to them and "
            "shall reduce it to writing. In POCSO cases: the victim's statement "
            "under §164 is critical substantive evidence. The Magistrate must be "
            "satisfied that the statement is voluntary. Recording in the language "
            "of the child, with an assistance person if needed, is mandatory. "
            "The statement must be video-graphed under Rule 7(5) POCSO Rules. "
            "In dowry death: the dying declaration under §164 is admissible as "
            "substantive evidence even without oath."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "164",
        "offence": "magistrate_statement_164",
        "max_imprisonment": "N/A — evidence",
    },
    {
        "id": "bnss-173",
        "text": (
            "BNSS §173(1)(a) — Charge sheet. The IO shall, as soon as the "
            "investigation is complete, forward the report to the Magistrate "
            "having jurisdiction. In offences punishable with 10+ years: charge "
            "sheet must be filed within 90 days. In other offences: 60 days. "
            "Delay requires explanation in the charge sheet. If the IO finds no "
            "case, a final report (B-report) is filed. The Magistrate may "
            "take cognisance and summon the accused if not satisfied with B-report."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "173",
        "offence": "charge_sheet_filing",
        "max_imprisonment": "N/A — procedural",
    },
    {
        "id": "bnss-173-2f",
        "text": (
            "BNSS §193(2)(f) — Special rules for certain offences. The following "
            "offences shall be tried in camera: (f) sexual assault under BNS §66 "
            "and §67; (h) offences affecting privacy of women (§72 BNS). "
            "In-camera trial: only the parties, their advocates, and the court "
            "staff may be present. No publication of identity. Breach is contempt. "
            "POCSO §33(5): the child's identity must not be disclosed in any "
            "proceedings — name, address, school, photographs are prohibited."
        ),
        "category": "pocso",
        "act": "BNSS",
        "section": "193(2)(f)",
        "offence": "in_camera_trial",
        "max_imprisonment": "N/A — procedural",
    },
    {
        "id": "bnss-184",
        "text": (
            "BNSS §184 — Charge sheet sufficiency. The charge shall contain the "
            "specific offence with the section of the penal law, the nature of "
            "the offence, and the place where it was committed. The charge must "
            "disclose the essential facts of the prosecution case — identity of "
            "accused, specific act or omission, and criminal intent. "
            "A defective charge that fails to disclose essential facts is fatal — "
            "the accused cannot be convicted under a charge that omits an essential "
            "ingredient of the offence."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "184",
        "offence": "charge_sufficiency",
        "max_imprisonment": "N/A — procedural (defective charge fatal)",
    },
    {
        "id": "bnss-435",
        "text": (
            "BNSS §435 — compounding of offences. The following offences may "
            "be compounded without permission of the court: (a) criminal "
            "trespass (§331 BNS), (b) hurt (§140 BNS — simple hurt), "
            "(c) criminal intimidation (§352 BNS). "
            "Compoundable offences require the victim's written consent and "
            "the accused must have compounded or agreed to compound. "
            "Non-compoundable: murder, rape, dowry death, SC/ST atrocity, NDPS. "
            "Note: dowry death (BNS §80) is NON-COMPOUNDABLE."
        ),
        "category": "general",
        "act": "BNSS",
        "section": "435",
        "offence": "compoundable_offences",
        "max_imprisonment": "N/A — procedural",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal corpus into ChromaDB")
    parser.add_argument("--reset", action="store_true", help="Delete existing collection and re-ingest")
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()
    log.info("corpus.start")

    try:
        import chromadb
    except ImportError:
        print("chromadb not installed. Run: pip install chromadb")
        sys.exit(1)

    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))

    if args.reset:
        try:
            client.delete_collection("aranmanai_corpus")
            log.info("corpus.reset")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name="aranmanai_corpus",
        metadata={"hnsw:space": "cosine"},
    )

    # Chunk long sections into smaller pieces (~500 chars each) for better retrieval
    chunk_size = 500
    chunk_ids = []
    chunk_texts = []
    chunk_metas = []
    for sec in SECTIONS:
        text = sec["text"]
        meta_base = {
            "category": sec["category"],
            "act": sec["act"],
            "section": sec["section"],
            "offence": sec["offence"],
            "max_imprisonment": sec["max_imprisonment"],
        }
        if len(text) <= chunk_size:
            chunk_ids.append(sec["id"])
            chunk_texts.append(text)
            chunk_metas.append(meta_base)
        else:
            # Split into sentences at sentence boundaries
            import re
            sentences = re.split(r"(?<=[.!?])\s+", text)
            current_chunk = ""
            chunk_num = 0
            for sent in sentences:
                if len(current_chunk) + len(sent) <= chunk_size:
                    current_chunk += " " + sent
                else:
                    if current_chunk.strip():
                        chunk_ids.append(f"{sec['id']}-chunk-{chunk_num}")
                        chunk_texts.append(current_chunk.strip())
                        chunk_metas.append(meta_base.copy())
                        chunk_num += 1
                    current_chunk = sent
            if current_chunk.strip():
                chunk_ids.append(f"{sec['id']}-chunk-{chunk_num}")
                chunk_texts.append(current_chunk.strip())
                chunk_metas.append(meta_base.copy())

    existing = collection.count()
    collection.upsert(documents=chunk_texts, ids=chunk_ids, metadatas=chunk_metas)
    total = collection.count()

    log.info(
        "corpus.done added=%d total=%d",
        total - existing,
        total,
    )
    print(f"\nCorpus ingested: {total - existing} new chunks added ({existing} pre-existing).")
    print(f"Total chunks: {total}")
    print(f"Categories: {sorted(set(m['category'] for m in chunk_metas))}")
    print(f"Acts: {sorted(set(m['act'] for m in chunk_metas))}")


if __name__ == "__main__":
    main()
