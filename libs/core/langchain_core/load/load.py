import importlib
import json
import os
from typing import Any, Optional

from langchain_core._api import beta
from langchain_core.load.mapping import (
    _JS_SERIALIZABLE_MAPPING,
    _OG_SERIALIZABLE_MAPPING,
    OLD_CORE_NAMESPACES_MAPPING,
    SERIALIZABLE_MAPPING,
)
from langchain_core.load.serializable import Serializable

DEFAULT_NAMESPACES = [
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_anthropic",
    "langchain_groq",
    "langchain_google_genai",
]

ALL_SERIALIZABLE_MAPPINGS = {
    **SERIALIZABLE_MAPPING,
    **OLD_CORE_NAMESPACES_MAPPING,
    **_OG_SERIALIZABLE_MAPPING,
    **_JS_SERIALIZABLE_MAPPING,
}


class Reviver:
    """Reviver for JSON objects."""

    def __init__(
        self,
        secrets_map: Optional[dict[str, str]] = None,
        valid_namespaces: Optional[list[str]] = None,
        secrets_from_env: bool = True,
        additional_import_mappings: Optional[
            dict[tuple[str, ...], tuple[str, ...]]
        ] = None,
    ) -> None:
        """Initialize the reviver.

        Args:
            secrets_map: A map of secrets to load. If a secret is not found in
                the map, it will be loaded from the environment if `secrets_from_env`
                is True. Defaults to None.
            valid_namespaces: A list of additional namespaces (modules)
                to allow to be deserialized. Defaults to None.
            secrets_from_env: Whether to load secrets from the environment.
                Defaults to True.
            additional_import_mappings: A dictionary of additional namespace mappings
                You can use this to override default mappings or add new mappings.
                Defaults to None.
        """
        self.secrets_from_env = secrets_from_env
        self.secrets_map = secrets_map or dict()
        # By default, only support langchain, but user can pass in additional namespaces
        self.valid_namespaces = (
            [*DEFAULT_NAMESPACES, *valid_namespaces]
            if valid_namespaces
            else DEFAULT_NAMESPACES
        )
        self.additional_import_mappings = additional_import_mappings or dict()
        self.import_mappings = (
            {
                **ALL_SERIALIZABLE_MAPPINGS,
                **self.additional_import_mappings,
            }
            if self.additional_import_mappings
            else ALL_SERIALIZABLE_MAPPINGS
        )

    def __call__(self, value: dict[str, Any]) -> Any:
        if (
            value.get("lc", None) == 1
            and value.get("type", None) == "secret"
            and value.get("id", None) is not None
        ):
            [key] = value["id"]
            if key in self.secrets_map:
                return self.secrets_map[key]
            else:
                if self.secrets_from_env and key in os.environ and os.environ[key]:
                    return os.environ[key]
                raise KeyError(f'Missing key "{key}" in load(secrets_map)')

        if (
            value.get("lc", None) == 1
            and value.get("type", None) == "not_implemented"
            and value.get("id", None) is not None
        ):
            raise NotImplementedError(
                "Trying to load an object that doesn't implement "
                f"serialization: {value}"
            )

        if (
            value.get("lc", None) == 1
            and value.get("type", None) == "constructor"
            and value.get("id", None) is not None
        ):
            [*namespace, name] = value["id"]

            if namespace[0] not in self.valid_namespaces:
                raise ValueError(f"Invalid namespace: {value}")

            # The root namespace "langchain" is not a valid identifier.
            if len(namespace) == 1 and namespace[0] == "langchain":
                raise ValueError(f"Invalid namespace: {value}")

            # If namespace is in known namespaces, try to use mapping
            key = tuple(namespace + [name])
            if namespace[0] in DEFAULT_NAMESPACES:
                # Get the importable path
                if key not in self.import_mappings:
                    raise ValueError(
                        "Trying to deserialize something that cannot "
                        "be deserialized in current version of langchain-core: "
                        f"{key}"
                    )
                import_path = self.import_mappings[key]
                # Split into module and name
                import_dir, import_obj = import_path[:-1], import_path[-1]
                # Import module
                mod = importlib.import_module(".".join(import_dir))
                # Import class
                cls = getattr(mod, import_obj)
            # Otherwise, load by path
            else:
                if key in self.additional_import_mappings:
                    import_path = self.import_mappings[key]
                    mod = importlib.import_module(".".join(import_path[:-1]))
                    name = import_path[-1]
                else:
                    mod = importlib.import_module(".".join(namespace))
                cls = getattr(mod, name)

            # The class must be a subclass of Serializable.
            if not issubclass(cls, Serializable):
                raise ValueError(f"Invalid namespace: {value}")

            # We don't need to recurse on kwargs
            # as json.loads will do that for us.
            kwargs = value.get("kwargs", dict())
            return cls(**kwargs)

        return value


@beta()
def loads(
    text: str,
    *,
    secrets_map: Optional[dict[str, str]] = None,
    valid_namespaces: Optional[list[str]] = None,
    secrets_from_env: bool = True,
    additional_import_mappings: Optional[dict[tuple[str, ...], tuple[str, ...]]] = None,
) -> Any:
    """Revive a LangChain class from a JSON string.
    Equivalent to `load(json.loads(text))`.

    Args:
        text: The string to load.
        secrets_map: A map of secrets to load. If a secret is not found in
            the map, it will be loaded from the environment if `secrets_from_env`
            is True. Defaults to None.
        valid_namespaces: A list of additional namespaces (modules)
            to allow to be deserialized. Defaults to None.
        secrets_from_env: Whether to load secrets from the environment.
            Defaults to True.
        additional_import_mappings: A dictionary of additional namespace mappings
            You can use this to override default mappings or add new mappings.
            Defaults to None.

    Returns:
        Revived LangChain objects.
    """
    return json.loads(
        text,
        object_hook=Reviver(
            secrets_map, valid_namespaces, secrets_from_env, additional_import_mappings
        ),
    )


@beta()
def load(
    obj: Any,
    *,
    secrets_map: Optional[dict[str, str]] = None,
    valid_namespaces: Optional[list[str]] = None,
    secrets_from_env: bool = True,
    additional_import_mappings: Optional[dict[tuple[str, ...], tuple[str, ...]]] = None,
) -> Any:
    """Revive a LangChain class from a JSON object. Use this if you already
    have a parsed JSON object, eg. from `json.load` or `orjson.loads`.

    Args:
        obj: The object to load.
        secrets_map: A map of secrets to load. If a secret is not found in
            the map, it will be loaded from the environment if `secrets_from_env`
            is True. Defaults to None.
        valid_namespaces: A list of additional namespaces (modules)
            to allow to be deserialized. Defaults to None.
        secrets_from_env: Whether to load secrets from the environment.
            Defaults to True.
        additional_import_mappings: A dictionary of additional namespace mappings
            You can use this to override default mappings or add new mappings.
            Defaults to None.

    Returns:
        Revived LangChain objects.
    """
    reviver = Reviver(
        secrets_map, valid_namespaces, secrets_from_env, additional_import_mappings
    )

    def _load(obj: Any) -> Any:
        if isinstance(obj, dict):
            # Need to revive leaf nodes before reviving this node
            loaded_obj = {k: _load(v) for k, v in obj.items()}
            return reviver(loaded_obj)
        if isinstance(obj, list):
            return [_load(o) for o in obj]
        return obj

    return _load(obj)
