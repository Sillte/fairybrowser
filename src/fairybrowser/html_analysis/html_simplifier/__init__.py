from .html_simplifier import HTMLSimplifier
from .models import (
    NodeProtectionRuleProtocol,
    SimplificationRuleProtocol,
    SubtreeProtectionRuleProtocol,
)
from .protection_rules import MainTagProtectionRule
from .simplification_rules import KeepRelevantAttributesRule, RemoveScriptAndStyleRule

__all__ = [
    "HTMLSimplifier",
    "KeepRelevantAttributesRule",
    "MainTagProtectionRule",
    "NodeProtectionRuleProtocol",
    "RemoveScriptAndStyleRule",
    "SimplificationRuleProtocol",
    "SubtreeProtectionRuleProtocol",
]

