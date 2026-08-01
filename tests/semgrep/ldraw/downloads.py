# ruff: noqa: D100, INP001


def _response_validator_matches(*_args: object, **_kwargs: object) -> bool | None:
    return None


def _resume_is_consistent(response: object, validator: object) -> bool:
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if _response_validator_matches(response=response, validator=validator) is False:
        return False
    matched = _response_validator_matches(response=response, validator=validator)
    # ruleid: pyldraw-resume-validation-must-fail-closed
    if matched is not False:
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
