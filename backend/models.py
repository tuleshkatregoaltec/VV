from sqlalchemy import Column, Integer, String, Float, Date
from database import Base


class Developers(Base):
    __tablename__ = "developers"

    id = Column(Integer, primary_key=True)
    participant_id = Column(String(200), nullable=False)
    developer_number = Column(String(100), nullable=False)
    developer_name_en = Column(Integer)
    registration_date = Column(Date)
    license_source_en = Column(Float)
    license_type_en = Column(String(100))
    legal_status_en = Column(String(100))
    webpage = Column(String(100))
    phone = Column(String(500))
    fax = Column(String(50))
    license_number = Column(String(50))
    license_issue_date = Column(Date)
    license_expiry_date = Column(Date)
    chamber_of_commerce_no = Column(String(20))

    def __repr__(self):
        return f"<Developer(name='{self.developer_name_en}', webpage='{self.webpage}')>"
