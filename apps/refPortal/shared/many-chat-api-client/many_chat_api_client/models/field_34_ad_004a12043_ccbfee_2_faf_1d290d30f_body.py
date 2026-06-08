from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Field34Ad004A12043Ccbfee2Faf1D290D30FBody")


@_attrs_define
class Field34Ad004A12043Ccbfee2Faf1D290D30FBody:
    """
    Attributes:
        subscriber_id (int):
        tag_name (str):
    """

    subscriber_id: int
    tag_name: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        tag_name = self.tag_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
                "tag_name": tag_name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        tag_name = d.pop("tag_name")

        field_34_ad_004a12043_ccbfee_2_faf_1d290d30f_body = cls(
            subscriber_id=subscriber_id,
            tag_name=tag_name,
        )

        field_34_ad_004a12043_ccbfee_2_faf_1d290d30f_body.additional_properties = d
        return field_34_ad_004a12043_ccbfee_2_faf_1d290d30f_body

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
