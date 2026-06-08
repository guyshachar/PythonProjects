from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.custom_field import CustomField


T = TypeVar("T", bound="Field1D7171252E09F4E25B5123F9484Ea3C1Response200Data")


@_attrs_define
class Field1D7171252E09F4E25B5123F9484Ea3C1Response200Data:
    """
    Attributes:
        field (Union[Unset, CustomField]):
    """

    field: Union[Unset, "CustomField"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.field, Unset):
            field = self.field.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if field is not UNSET:
            field_dict["field"] = field

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.custom_field import CustomField

        d = dict(src_dict)
        _field = d.pop("field", UNSET)
        field: Union[Unset, CustomField]
        if isinstance(_field, Unset):
            field = UNSET
        else:
            field = CustomField.from_dict(_field)

        field_1d7171252e09f4e25b5123f9484_ea_3c1_response_200_data = cls(
            field=field,
        )

        field_1d7171252e09f4e25b5123f9484_ea_3c1_response_200_data.additional_properties = d
        return field_1d7171252e09f4e25b5123f9484_ea_3c1_response_200_data

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
