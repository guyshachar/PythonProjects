from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.page import Page


T = TypeVar("T", bound="B26C074B3783Eb6E888C62324B17268CResponse200")


@_attrs_define
class B26C074B3783Eb6E888C62324B17268CResponse200:
    """
    Attributes:
        status (Union[Unset, str]):  Example: success.
        data (Union[Unset, Page]):
    """

    status: Union[Unset, str] = UNSET
    data: Union[Unset, "Page"] = UNSET
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
        from ..models.page import Page

        d = dict(src_dict)
        status = d.pop("status", UNSET)

        _data = d.pop("data", UNSET)
        data: Union[Unset, Page]
        if isinstance(_data, Unset):
            data = UNSET
        else:
            data = Page.from_dict(_data)

        b26c074b3783_eb_6e888c62324b17268c_response_200 = cls(
            status=status,
            data=data,
        )

        b26c074b3783_eb_6e888c62324b17268c_response_200.additional_properties = d
        return b26c074b3783_eb_6e888c62324b17268c_response_200

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
