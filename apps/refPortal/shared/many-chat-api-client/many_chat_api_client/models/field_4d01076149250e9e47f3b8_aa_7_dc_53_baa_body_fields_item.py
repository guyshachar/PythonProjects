from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem")


@_attrs_define
class Field4D01076149250E9E47F3B8Aa7Dc53BaaBodyFieldsItem:
    """
    Attributes:
        field_id (Union[Unset, int]):
        field_name (Union[Unset, str]):
        field_value (Union[Unset, Any]): string, integer or boolean (see method description) Example: 'string', 123,
            true, '2018-07-18', '2018-07-02T00:00:00+00:00'.
    """

    field_id: Union[Unset, int] = UNSET
    field_name: Union[Unset, str] = UNSET
    field_value: Union[Unset, Any] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field_id = self.field_id

        field_name = self.field_name

        field_value = self.field_value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if field_id is not UNSET:
            field_dict["field_id"] = field_id
        if field_name is not UNSET:
            field_dict["field_name"] = field_name
        if field_value is not UNSET:
            field_dict["field_value"] = field_value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        field_id = d.pop("field_id", UNSET)

        field_name = d.pop("field_name", UNSET)

        field_value = d.pop("field_value", UNSET)

        field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body_fields_item = cls(
            field_id=field_id,
            field_name=field_name,
            field_value=field_value,
        )

        field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body_fields_item.additional_properties = d
        return field_4d01076149250e9e47f3b8_aa_7_dc_53_baa_body_fields_item

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
