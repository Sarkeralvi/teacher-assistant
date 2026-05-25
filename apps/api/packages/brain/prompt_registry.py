from packages.brain.schemas import ModelPolicy

PROMPT_VERSIONS: dict[ModelPolicy, str] = {
    ModelPolicy.MOCK_GRADING: "mock-grading-v1",
}


def get_prompt_version(policy: ModelPolicy) -> str:
    return PROMPT_VERSIONS[policy]
