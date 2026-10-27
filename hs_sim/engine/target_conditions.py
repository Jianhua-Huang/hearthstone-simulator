"""Finite native target activation over original accepted play conditions."""
from collections.abc import Mapping


TARGET_CONDITIONS = ('combo','outcast','finale','quickdraw','manathirst','unless_quickdraw')


def target_condition_keyword(condition):
    """The inverse native declaration still requires printed Quickdraw."""
    if type(condition) is not str or condition not in TARGET_CONDITIONS:
        raise ValueError('Unsupported native target condition')
    return 'quickdraw' if condition == 'unless_quickdraw' else condition


def target_condition_active(condition, conditions):
    """No derived saved flag: invert the same original Quickdraw boolean."""
    if condition is None:return True
    key = target_condition_keyword(condition)
    try:
        value = conditions[key] if isinstance(conditions,Mapping) else getattr(conditions,key)
    except (KeyError,AttributeError) as error:
        raise ValueError('Target activation lost its original '+key+' fact') from error
    if type(value) is not bool:raise ValueError('Target activation requires an original boolean')
    return not value if condition == 'unless_quickdraw' else value
