"""Seed the database with pilot data: 20 realistic cases across 5 offence types.

Used for:
- Demo of the SP dashboard / daily calendar / witness production
- Pilot measurement (the 20-30 case pilot per the build plan)
- Integration tests (replace mock data with real-shaped seeded data)

Usage:
    python scripts/seed_pilot_data.py            # seed 20 cases
    python scripts/seed_pilot_data.py --clear   # wipe first, then seed

Offence distribution (matches TN/SC-ST priorities per NCRB + BPRD):
- 5 POCSO  (sexual offences against children)
- 4 murder
- 4 NDPS   (drugs)
- 4 dowry death / 304B BNS
- 3 SC/ST atrocity (PoA Act)
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aranmanai.config import get_settings
from aranmanai.db import Base, engine, init_db, SessionLocal  # noqa: F401 — engine is callable
from aranmanai.db.models.case import Case, CaseStage, CaseStatus
from aranmanai.db.models.evidence import Evidence, EvidenceType, FslStatus, EvidenceChainStatus
from aranmanai.db.models.hearing import Hearing
from aranmanai.db.models.user import User, UserRole
from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessPrepStatus, WitnessType
from aranmanai.observability import get_logger, setup_logging
from aranmanai.security import encrypt_field, hash_password

log = get_logger(__name__)


# ── Realistic Tamil / Indian data (anonymous, fictional) ───────────

COMPLAINANTS = {
    "pocso": [
        ("Kavitha", "f", "98421xxxxx", "Vellore"),
        ("Lakshmi", "f", "98422xxxxx", "Tirupattur"),
        ("Revathi", "f", "98423xxxxx", "Gudiyattam"),
        ("Sangeetha", "f", "98424xxxxx", "Vaniyambadi"),
        ("Anitha", "f", "98425xxxxx", "Ambur"),
    ],
    "murder": [
        ("Murugan", "m", "98431xxxxx", "Vellore"),
        ("Selvam", "m", "98432xxxxx", "Tirupattur"),
        ("Kannan", "m", "98433xxxxx", "Gudiyattam"),
        ("Ravi", "m", "98434xxxxx", "Vaniyambadi"),
    ],
    "ndps": [
        ("Suresh", "m", "98441xxxxx", "Vellore"),
        ("Karthik", "m", "98442xxxxx", "Tirupattur"),
        ("Velu", "m", "98443xxxxx", "Gudiyattam"),
        ("Mani", "m", "98444xxxxx", "Ambur"),
    ],
    "dowry": [
        ("Priya", "f", "98451xxxxx", "Vellore"),
        ("Divya", "f", "98452xxxxx", "Tirupattur"),
        ("Saranya", "f", "98453xxxxx", "Gudiyattam"),
        ("Nithya", "f", "98454xxxxx", "Vaniyambadi"),
    ],
    "scst": [
        ("Murthy", "m", "98461xxxxx", "Vellore"),
        ("Selvi", "f", "98462xxxxx", "Tirupattur"),
        ("Kavitha", "f", "98463xxxxx", "Gudiyattam"),
    ],
}

ACCUSED = {
    "pocso": [("Palani", "m", 35), ("Suresh", "m", 42), ("Ravi", "m", 28), ("Mohan", "m", 50), ("Kumar", "m", 38)],
    "murder": [("Siva", "m", 32), ("Velraj", "m", 45), ("Anand", "m", 28), ("Karthik", "m", 35)],
    "ndps": [("Faisal", "m", 30), ("Riyaz", "m", 35), ("Imran", "m", 28), ("Salman", "m", 40)],
    "dowry": [("Vinod", "m", 35), ("Prakash", "m", 40), ("Suresh", "m", 45), ("Rajesh", "m", 38)],
    "scst": [("Ganesan", "m", 50), ("Muniswamy", "m", 45), ("Sekar", "m", 55)],
}

WITNESS_NAMES = [
    "Ramu", "Gopal", "Krishnan", "Babu", "Mani", "Selvi", "Valli", "Lakshmi",
    "Suresh", "Anitha", "Kavitha", "Murugan", "Kannan", "Revathi", "Saranya",
    "Velu", "Karthik", "Sangeetha", "Palani", "Selvam",
]

# Hostile probability per offence type (based on BPRD acquittal data)
HOSTILE_PROB = {
    "pocso": 0.20,   # POCSO witnesses usually cooperative
    "murder": 0.45,   # murder witnesses often turn hostile
    "ndps": 0.55,     # NDPS witnesses turn hostile frequently
    "dowry": 0.60,    # dowry witnesses — family pressure
    "scst": 0.50,     # SC/ST witnesses — coercion by accused
}

# BNS / BNSS / BSA section mapping per offence (post-1-July-2024)
SECTION_MAP = {
    "pocso": {
        "bns": ["BNS §63 (rape)", "BNS §64 (rape, aggravated)", "POCSO §6 (penetrative sexual assault)"],
        "bnss": ["BNSS §173(1)(a) (rape)", "BNSS §193(2)(f) (POCSO — in-camera)"],
        "bsa": ["BSA §63(4)(c) (medical evidence)"],
    },
    "murder": {
        "bns": ["BNS §103(1) (murder)", "BNS §103(2) (murder by group)"],
        "bnss": ["BNSS §173(1)(a) (cognizable)"],
        "bsa": ["BSA §27 (post-mortem)", "BSA §63(4)(c) (forensic evidence)"],
    },
    "ndps": {
        "bns": ["NDPS §20 (ganja)", "NDPS §22 (cocaine)", "NDPS §25 (heroin)"],
        "bnss": ["BNSS §173(1)(a) (cognizable)"],
        "bsa": ["BSA §63(4)(c) (forensic)"],
    },
    "dowry": {
        "bns": ["BNS §80 (dowry death)", "BNS §85 (cruelty)", "BNS §85(2)(ii) (abetment to suicide)"],
        "bnss": ["BNSS §173(1)(a) (cognizable)"],
        "bsa": ["BSA §27 (post-mortem)"],
    },
    "scst": {
        "bns": ["BNS §103(1) (murder)", "BNS §78 (hurt)", "BNS §79 (grievous hurt)"],
        "bnss": ["BNSS §173(1)(a)", "PoA §18A inquiry"],
        "bsa": ["BSA §27 (medical evidence)"],
        "poa": ["PoA §3(1)(r)", "PoA §3(1)(s)", "PoA §18A"],
    },
}

CASE_FACTS = {
    "pocso": (
        "The accused, a neighbour of the victim's family, committed penetrative sexual assault "
        "on the 9-year-old victim on {date} at her residence in {place}. The victim disclosed the "
        "incident to her mother (complainant) on the same evening. The IO recorded the victim's "
        "statement under Section 164 BNSS (Magistrate) on {date2}. MLC confirmed fresh injuries. "
        "FSL report on the victim's clothes and the accused's DNA profile is positive."
    ),
    "murder": (
        "The accused stabbed the victim (35, male, daily-wage labourer) following a quarrel over "
        "money on {date} at {place}. The accused was apprehended at the scene by local witnesses "
        "and confessed under Section 27 of the BSA (recovery of weapon from his house). "
        "Post-mortem confirmed the cause of death. The weapon (knife) is in custody."
    ),
    "ndps": (
        "On {date}, acting on intel, a police team intercepted the accused at {place} with 12 kg "
        "of ganja in two gunny bags. NDPS Section 50 notice was issued (accused's signature on "
        "file). Two independent civilian panch witnesses were present at search and seizure. "
        "Samples drawn and sent to FSL. FSL report returned positive for cannabis."
    ),
    "dowry": (
        "The deceased (29, married 5 years, one daughter) was found dead by hanging at her marital "
        "home on {date} in {place}. The deceased's mother (complainant) alleges repeated "
        "harassment for dowry (₹15 lakh demanded for a car). The Section 174 BNSS inquest "
        "noted strangulation marks inconsistent with suicide. The accused (husband, mother-in-law) "
        "are arrested."
    ),
    "scst": (
        "The accused (upper-caste, village leader) publicly humiliated the complainant (SC) by "
        "caste slurs and physical assault at the village common area on {date} in {place}. The "
        "incident was witnessed by 5 villagers. The complainant filed a complaint the next day. "
        "18A inquiry was conducted and confirmed caste-based intent."
    ),
}


# ── Seed routines ────────────────────────────────────────────────────

def _ensure_io(db, district: str) -> User:
    """Ensure at least one IO user exists for the district."""
    io = db.query(User).filter(User.role == UserRole.IO, User.district == district).first()
    if io:
        return io
    settings = get_settings()
    io = User(
        username="io_1",
        hashed_password=hash_password("Aranmanai!Dev!2026"),
        name_encrypted=encrypt_field("IO Demo"),
        role=UserRole.IO,
        district=district,
        is_active=True,
    )
    db.add(io)
    db.commit()
    db.refresh(io)
    return io


def _ensure_pp(db, district: str) -> User:
    """Ensure at least one PP user exists."""
    pp = db.query(User).filter(User.role == UserRole.PP, User.district == district).first()
    if pp:
        return pp
    pp = User(
        username="pp_1",
        hashed_password=hash_password("Aranmanai!Dev!2026"),
        name_encrypted=encrypt_field("PP Demo"),
        role=UserRole.PP,
        district=district,
        is_active=True,
    )
    db.add(pp)
    db.commit()
    db.refresh(pp)
    return pp


def _witness_for(db, case_id: str, idx: int, name: str, type_: WitnessType,
                category: WitnessCategory, hostile_reason: str | None,
                prep_status: WitnessPrepStatus) -> Witness:
    w = Witness(
        case_id=case_id,
        name_encrypted=encrypt_field(name),
        contact_encrypted=encrypt_field(f"98{random.randint(400000000, 499999999)}"),
        type=type_,
        category=category,
        language="ta",
        prep_status=prep_status,
        hostile_reason=hostile_reason if category == WitnessCategory.HOSTILE else None,
        last_contact=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 14)),
    )
    db.add(w)
    db.flush()
    return w


def _evidence_for(db, case_id: str, type_: EvidenceType, chain: EvidenceChainStatus,
                 fsl: FslStatus) -> Evidence:
    desc_map = {
        EvidenceType.DOCUMENT: "Charge sheet / FIR copy",
        EvidenceType.WITNESS_TESTIMONY: "164 BNSS statement",
        EvidenceType.FSL: "FSL report",
        EvidenceType.ELECTRONIC: "CCTV / mobile records",
        EvidenceType.PHYSICAL: "Recovered material evidence",
        EvidenceType.MEDICAL: "MLC / post-mortem report",
    }
    e = Evidence(
        case_id=case_id,
        type=type_,
        description=desc_map.get(type_, "Evidence item"),
        chain_status=chain,
        fsl_status=fsl,
    )
    db.add(e)
    db.flush()
    return e


def _hearing_for(db, case_id: str, stage: str, days_from_now: int,
                pp_present: bool, defense_present: bool, accused_present: bool,
                witnesses: list) -> Hearing:
    h = Hearing(
        case_id=case_id,
        date=datetime.now(timezone.utc) + timedelta(days=days_from_now),
        stage=stage,
        pp_present=pp_present,
        defense_present=defense_present,
        accused_present=accused_present,
        witness_ids_present=[w.id for w in witnesses[:2]],
    )
    db.add(h)
    db.flush()
    return h


def seed_case(db, idx: int, offence: str, district: str) -> Case:
    """Seed one case with witnesses, evidence, hearings, and an IO/PP."""
    io = _ensure_io(db, district)
    pp = _ensure_pp(db, district)
    case_id = f"case-{offence}-{idx:03d}"
    fir_no = f"FIR/{district[:3].upper()}/{random.randint(2024, 2026):04d}/{random.randint(100, 999):03d}"

    case_stage = random.choice([
        CaseStage.CHARGE_SHEET, CaseStage.EVIDENCE, CaseStage.ARGUMENT,
    ])
    case_status = random.choice([CaseStatus.OPEN, CaseStatus.CHARGE_SHEETED, CaseStatus.TRIAL])

    date_str = (datetime.now() - timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d")
    date2_str = (datetime.now() - timedelta(days=random.randint(20, 360))).strftime("%Y-%m-%d")
    place = random.choice(["Vellore", "Tirupattur", "Gudiyattam", "Vaniyambadi", "Ambur"])
    facts = CASE_FACTS[offence].format(date=date_str, date2=date2_str, place=place)

    sections = SECTION_MAP[offence]

    case = Case(
        id=case_id,
        fir_no=fir_no,
        bns_sections=sections["bns"],
        bnss_sections=sections["bnss"],
        bsa_sections=sections["bsa"],
        poa_sections=sections.get("poa", []),
        io_id=io.id,
        district=district,
        court=random.choice(["District Court", "Sessions Court", "POCSO Court", "Special Court (SC/ST)"]),
        judge=random.choice(["Justice Anand", "Justice Bhavani", "Justice Chandran", "Justice Devi"]),
        pp_id=pp.id,
        status=case_status,
        stage=case_stage,
        next_hearing=None,  # populated below
        facts=facts,
        is_poa_act_case=offence == "scst",
    )
    db.add(case)
    db.flush()

    # Witnesses (3-6 per case)
    n_witnesses = random.randint(3, 6)
    hostile_prob = HOSTILE_PROB[offence]
    for i in range(n_witnesses):
        name = random.choice(WITNESS_NAMES)
        is_hostile = random.random() < hostile_prob
        if is_hostile:
            category = WitnessCategory.HOSTILE
            type_ = random.choice([WitnessType.EYEWITNESS, WitnessType.VICTIM])
            hostile_reason = random.choice([
                "threats from accused family",
                "in-family pressure (witness is relative of accused)",
                "bought off by accused",
                "fear of retaliation",
            ])
            prep_status = random.choice([WitnessPrepStatus.UNTOUCHED, WitnessPrepStatus.PREPPED, WitnessPrepStatus.PREPPED])
        else:
            category = random.choice([WitnessCategory.SUPPORTIVE, WitnessCategory.NEUTRAL])
            type_ = random.choice([WitnessType.EYEWITNESS, WitnessType.VICTIM, WitnessType.EXPERT])
            hostile_reason = None
            prep_status = random.choice([WitnessPrepStatus.UNTOUCHED, WitnessPrepStatus.PREPPED, WitnessPrepStatus.READY, WitnessPrepStatus.READY, WitnessPrepStatus.READY])
        _witness_for(db, case_id, i, f"{name} {i+1}", type_, category, hostile_reason, prep_status)

    # Evidence (2-5 items)
    n_evidence = random.randint(2, 5)
    for _ in range(n_evidence):
        type_ = random.choice(list(EvidenceType))
        chain = random.choice([EvidenceChainStatus.SEALED, EvidenceChainStatus.SEALED, EvidenceChainStatus.SEALED, EvidenceChainStatus.BROKEN])
        fsl = random.choice(list(FslStatus))
        has_cctv = random.random() < 0.3
        _evidence_for(db, case_id, type_, chain, fsl)

    # Hearings: 1-3 past hearings + 1 upcoming
    n_past_hearings = random.randint(1, 3)
    for i in range(n_past_hearings):
        days_ago = random.randint(15, 180)
        _hearing_for(
            db, case_id, "witness_examination", -days_ago,
            pp_present=True, defense_present=True, accused_present=random.random() < 0.85,
            witnesses=[],
        )
    # Upcoming hearing
    days_ahead = random.randint(0, 30)
    if days_ahead == 0:
        days_ahead = 1  # always at least 1 day out
    case.next_hearing = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    _hearing_for(
        db, case_id, "witness_examination", days_ahead,
        pp_present=True, defense_present=True, accused_present=random.random() < 0.85,
        witnesses=[],
    )

    return case


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Aranmanai with pilot data")
    parser.add_argument("--clear", action="store_true", help="Wipe existing case/witness/hearing/evidence rows before seeding")
    parser.add_argument("--offences", default="pocso,murder,ndps,dowry,scst",
                        help="Comma-separated offence types to seed")
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()
    district = settings.district or "default-district"

    log.info("seed.start", clear=args.clear, district=district)
    init_db()
    db = SessionLocal()
    try:
        if args.clear:
            log.info("seed.clear")
            Base.metadata.drop_all(bind=engine())
            Base.metadata.create_all(bind=engine())
            db.commit()
            log.info("seed.schema_recreated")

        offences = args.offences.split(",")
        # Distribution: 5 POCSO, 4 murder, 4 NDPS, 4 dowry, 3 SC/ST
        distribution = {
            "pocso": 5, "murder": 4, "ndps": 4, "dowry": 4, "scst": 3,
        }
        idx = 0
        for offence in offences:
            count = distribution.get(offence.strip(), 2)
            for i in range(count):
                case = seed_case(db, idx, offence.strip(), district)
                log.info("seed.case", id=case.id, fir=case.fir_no, offence=offence)
                idx += 1
        db.commit()
        log.info("seed.done", total=idx)
        print(f"\nSeeded {idx} cases across {len(offences)} offence types.")
        print(f"  Default admin: admin / Aranmanai!Dev!2026")
        print(f"  District: {district}")
        print(f"  Login: POST /api/v1/auth/login")
        print(f"  Then: GET /api/v1/cms/calendar/today or GET /api/v1/cms/sp-dashboard")
    finally:
        db.close()


if __name__ == "__main__":
    main()
