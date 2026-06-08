from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body_fields_item import (
        Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem,
    )


T = TypeVar("T", bound="Field4D01076149250E9E47F3B8Aa7Dc53BaaBody")


@_attrs_define
class Field4D01076149250E9E47F3B8Aa7Dc53BaaBody:
    """
    Attributes:
        subscriber_id (int):
        fields (list['Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem']):
    """

    subscriber_id: int
    fields: list["Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        fields = []
        for fields_item_data in self.fields:
            fields_item = fields_item_data.to_dict()
            fields.append(fields_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
                "fields": fields,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body_fields_item import (
            Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem,
        )

        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        fields = []
        _fields = d.pop("fields")
        for fields_item_data in _fields:
            fields_item = Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem.from_dict(fields_item_data)

            fields.append(fields_item)

        field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body = cls(
            subscriber_id=subscriber_id,
            fields=fields,
        )

        field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body.additional_properties = d
        return field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body

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
