"""Skill registry: every capability of the APR Assistant, each independently usable."""


def build_registry():
    from app.skills.base import SkillRegistry
    from app.skills.core_skills import ArtistsSkill, CoordinatorsSkill, EventsSkill, InstitutionsSkill, ProgramSkill
    from app.skills.output_skills import (AprSkill, BankSkill, DocumentsSkill, GuidelinesSkill, LookupsSkill,
                                          OutboxSkill, PaymentsSkill, PostersSkill)
    from app.skills.batch import BatchSkill
    reg = SkillRegistry()
    for cls in (ProgramSkill, EventsSkill, ArtistsSkill, InstitutionsSkill, CoordinatorsSkill, AprSkill, DocumentsSkill,
                PaymentsSkill, GuidelinesSkill, OutboxSkill, PostersSkill, BankSkill, LookupsSkill, BatchSkill):
        reg.register(cls())
    return reg
