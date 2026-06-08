from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.field_327327a53f87_fecaeb_9f7_cd_69c0433_af_body_fields_item import (
        Field327327A53F87Fecaeb9F7Cd69C0433AfBodyFieldsItem,
    )


T = TypeVar("T", bound="Field327327A53F87Fecaeb9F7Cd69C0433AfBody")


@_attrs_define
class Field327327A53F87Fecaeb9F7Cd69C0433AfBody:
    """
    Attributes:
        fields (list['Field327327A53F87Fecaeb9F7Cd69C0433AfBodyFieldsItem']):
    """

    fields: list["Field327327A53F87Fecaeb9F7Cd69C0433AfBodyFieldsItem"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        fields = []
        for fields_item_data in self.fields:
            fields_item = fields_item_data.to_dict()
            fields.append(fields_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "fields": fields,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.field_327327a53f87_fecaeb_9f7_cd_69c0433_af_body_fields_item import (
            Field327327A53F87Fecaeb9F7Cd69C0433AfBodyFieldsItem,
        )

        d = dict(src_dict)
        fields = []
        _fields = d.pop("fields")
        for fields_item_data in _fields:
            fields_item = Field327327A53F87Fecaeb9F7Cd69C0433AfBodyFieldsItem.from_dict(fields_item_data)

            fields.append(fields_item)

        field_327327a53f87_fecaeb_9f7_cd_69c0433_af_body = cls(
            fields=fields,
        )

        field_327327a53f87_fecaeb_9f7_cd_69c0433_af_body.additional_properties = d
        return field_327327a53f87_fecaeb_9f7_cd_69c0433_af_body

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
