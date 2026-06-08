from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200_data import (
        Field388714B65C83021Aa8B1Bb78481Fb983Response200Data,
    )


T = TypeVar("T", bound="Field388714B65C83021Aa8B1Bb78481Fb983Response200")


@_attrs_define
class Field388714B65C83021Aa8B1Bb78481Fb983Response200:
    """
    Attributes:
        status (Union[Unset, str]):  Example: success.
        data (Union[Unset, Field388714B65C83021Aa8B1Bb78481Fb983Response200Data]):
    """

    status: Union[Unset, str] = UNSET
    data: Union[Unset, "Field388714B65C83021Aa8B1Bb78481Fb983Response200Data"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        data: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.data, Unset):
            data = self.data.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if status is not UNSET:
            field_dict["status"] = status
        if data is not UNSET:
            field_dict["data"] = data

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200_data import (
            Field388714B65C83021Aa8B1Bb78481Fb983Response200Data,
        )

        d = dict(src_dict)
        status = d.pop("status", UNSET)

        _data = d.pop("data", UNSET)
        data: Union[Unset, Field388714B65C83021Aa8B1Bb78481Fb983Response200Data]
        if isinstance(_data, Unset):
            data = UNSET
        else:
            data = Field388714B65C83021Aa8B1Bb78481Fb983Response200Data.from_dict(_data)

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200 = cls(
            status=status,
            data=data,
        )

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200.additional_properties = d
        return field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200

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
