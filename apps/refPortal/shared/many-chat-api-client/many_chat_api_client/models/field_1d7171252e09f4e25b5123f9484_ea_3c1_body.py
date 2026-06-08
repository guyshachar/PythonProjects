from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Field1D7171252E09F4E25B5123F9484Ea3C1Body")


@_attrs_define
class Field1D7171252E09F4E25B5123F9484Ea3C1Body:
    """
    Attributes:
        caption (str):  Example: My custom field name.
        type_ (str): Value from list: text, number, date, datetime, boolean Example: text.
        description (Union[Unset, str]):  Example: This field store my custom field name.
    """

    caption: str
    type_: str
    description: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        caption = self.caption

        type_ = self.type_

        description = self.description

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "caption": caption,
                "type": type_,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        caption = d.pop("caption")

        type_ = d.pop("type")

        description = d.pop("description", UNSET)

        field_1d7171252e09f4e25b5123f9484_ea_3c1_body = cls(
            caption=caption,
            type_=type_,
            description=description,
        )

        field_1d7171252e09f4e25b5123f9484_ea_3c1_body.additional_properties = d
        return field_1d7171252e09f4e25b5123f9484_ea_3c1_body

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
