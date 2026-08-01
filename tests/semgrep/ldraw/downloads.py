# ruff: noqa: D100, E712, INP001, PLR0911


def _response_validator_matches(*_args: object, **_kwargs: object) -> bool | None:
    return None


def _resume_is_consistent(response: object, validator: object) -> bool:
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if _response_validator_matches(response=response, validator=validator) is False:
        return False
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if _response_validator_matches(response, validator) == False:
        return False
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if _response_validator_matches(response, validator) != False:
        return True
    matched = _response_validator_matches(response=response, validator=validator)
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if matched is not False:
        return True
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if matched == False:
        return False
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if matched != False:
        return True
    # ok: pyldraw-resume-validation-must-fail-closed
    if _response_validator_matches(response=response, validator=validator) is not True:
        return False
    # ruleid: pyldraw-resume-validation-must-fail-closed
    return (
        _response_validator_matches(
            response=response,
            validator=validator,
        )
        is not False
    )
