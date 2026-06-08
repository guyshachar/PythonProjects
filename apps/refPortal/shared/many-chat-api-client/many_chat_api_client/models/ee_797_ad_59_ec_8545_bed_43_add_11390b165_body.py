from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Ee797Ad59Ec8545Bed43Add11390B165Body")


@_attrs_define
class Ee797Ad59Ec8545Bed43Add11390B165Body:
    """
    Attributes:
        subscriber_id (int):
        tag_id (int):
    """

    subscriber_id: int
    tag_id: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        tag_id = self.tag_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
                "tag_id": tag_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        tag_id = d.pop("tag_id")

        ee_797_ad_59_ec_8545_bed_43_add_11390b165_body = cls(
            subscriber_id=subscriber_id,
            tag_id=tag_id,
        )

        ee_797_ad_59_ec_8545_bed_43_add_11390b165_body.additional_properties = d
        return ee_797_ad_59_ec_8545_bed_43_add_11390b165_body

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
