from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Field63284Ce7970087A42458D5A2C2594C1BBody")


@_attrs_define
class Field63284Ce7970087A42458D5A2C2594C1BBody:
    """
    Attributes:
        field_name (str):
        field_value (Any): string, integer or boolean (see method description) Example: 'string', 123, true,
            '2018-07-18', '2018-07-02T00:00:00+00:00'.
    """

    field_name: str
    field_value: Any
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field_name = self.field_name

        field_value = self.field_value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "field_name": field_name,
                "field_value": field_value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        field_name = d.pop("field_name")

        field_value = d.pop("field_value")

        field_63284_ce_7970087a42458d5a2c2594c1b_body = cls(
            field_name=field_name,
            field_value=field_value,
        )

        field_63284_ce_7970087a42458d5a2c2594c1b_body.additional_properties = d
        return field_63284_ce_7970087a42458d5a2c2594c1b_body

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
