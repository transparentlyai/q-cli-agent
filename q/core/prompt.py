# q/core/prompt.py
# Q: no-change
import os


def load_prompt(prompt_path: str, **kwargs) -> str:
    """
    Loads a prompt from the given path and substitutes variables.

    Args:
        prompt_path: Path to the prompt file.
        **kwargs: Variables to substitute in the prompt.

    Returns:
        The prompt with variables substituted.
    """
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    with open(prompt_path, "r") as f:
        prompt_template = f.read()

    try:
        populated_prompt = prompt_template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Missing variable in prompt template: {e}") from e

    return populated_prompt


if __name__ == "__main__":
    # Example usage:
    prompt_file = "my_prompt.txt"
    with open(prompt_file, "w") as f:
        f.write("This is a prompt with {name} and {adjective} words.")

    variables = {"name": "Q", "adjective": "creative"}
    populated_prompt = load_prompt(prompt_file, **variables)
    print(f"Populated Prompt:\n{populated_prompt}")

    os.remove(prompt_file)  # Cleanup example file

