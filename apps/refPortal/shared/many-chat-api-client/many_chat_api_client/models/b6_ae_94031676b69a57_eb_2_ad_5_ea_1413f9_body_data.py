from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData")


@_attrs_define
class B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData:
    """ """

    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body_data = cls()

        b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body_data.additional_properties = d
        return b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body_data

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
