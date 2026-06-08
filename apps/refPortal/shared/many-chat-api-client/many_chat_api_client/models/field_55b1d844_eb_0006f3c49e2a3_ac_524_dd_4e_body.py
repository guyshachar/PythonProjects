from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody")


@_attrs_define
class Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody:
    """
    Attributes:
        tag_id (int):  Example: 123.
    """

    tag_id: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tag_id = self.tag_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tag_id": tag_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tag_id = d.pop("tag_id")

        field_55b1d844_eb_0006f3c49e2a3_ac_524_dd_4e_body = cls(
            tag_id=tag_id,
        )

        field_55b1d844_eb_0006f3c49e2a3_ac_524_dd_4e_body.additional_properties = d
        return field_55b1d844_eb_0006f3c49e2a3_ac_524_dd_4e_body

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
