from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Field02235C5D38C1F33Af18A296D331E5A35Body")


@_attrs_define
class Field02235C5D38C1F33Af18A296D331E5A35Body:
    """
    Attributes:
        tag_name (str):  Example: MyTagName.
    """

    tag_name: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tag_name = self.tag_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tag_name": tag_name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tag_name = d.pop("tag_name")

        field_02235c5d38c1f33_af_18a296d331e5a35_body = cls(
            tag_name=tag_name,
        )

        field_02235c5d38c1f33_af_18a296d331e5a35_body.additional_properties = d
        return field_02235c5d38c1f33_af_18a296d331e5a35_body

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
