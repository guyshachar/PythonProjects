from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Field4032722E43E4B967E07D1B1279942254Body")


@_attrs_define
class Field4032722E43E4B967E07D1B1279942254Body:
    """
    Attributes:
        field_id (int):
        field_value (Any): string, integer or boolean (see method description) Example: 'string', 123, true,
            '2018-07-18', '2018-07-02T00:00:00+00:00'.
    """

    field_id: int
    field_value: Any
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field_id = self.field_id

        field_value = self.field_value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "field_id": field_id,
                "field_value": field_value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        field_id = d.pop("field_id")

        field_value = d.pop("field_value")

        field_4032722e43e4b967e07d1b1279942254_body = cls(
            field_id=field_id,
            field_value=field_value,
        )

        field_4032722e43e4b967e07d1b1279942254_body.additional_properties = d
        return field_4032722e43e4b967e07d1b1279942254_body

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
