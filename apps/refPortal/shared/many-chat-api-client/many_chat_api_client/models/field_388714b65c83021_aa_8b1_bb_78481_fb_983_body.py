from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Field388714B65C83021Aa8B1Bb78481Fb983Body")


@_attrs_define
class Field388714B65C83021Aa8B1Bb78481Fb983Body:
    """
    Attributes:
        name (str):  Example: My bot name.
        type_ (str): Value from list: text, number, date, datetime, boolean Example: text.
        description (Union[Unset, str]):  Example: This field store my bot name.
        value (Union[Unset, Any]): string, integer or boolean (see method description for setBotField) Example:
            'string', 123, true, '2018-07-18', '2018-07-02T00:00:00+00:00'.
    """

    name: str
    type_: str
    description: Union[Unset, str] = UNSET
    value: Union[Unset, Any] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        type_ = self.type_

        description = self.description

        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "type": type_,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        type_ = d.pop("type")

        description = d.pop("description", UNSET)

        value = d.pop("value", UNSET)

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_body = cls(
            name=name,
            type_=type_,
            description=description,
            value=value,
        )

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_body.additional_properties = d
        return field_388714b65c83021_aa_8b1_bb_78481_fb_983_body

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
