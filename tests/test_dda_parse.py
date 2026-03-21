import unittest

from holocron.sources.dda.parse import parse_plot_info, project_area_row, plot_feature_row


PLOT_INFO_HTML = """
<label>Old Numbers</label><div class="form-info-dda">123, 124</div>
<label>Project Name</label><div class="form-info-dda">Example Project</div>
<label>Community Name</label><div class="form-info-dda">Dubai Design District</div>
<label>Plot Area</label><div class="form-info-dda">1,234 M (13,282 Ft)</div>
<label>Maximum GFA</label><div class="form-info-dda">2,000 M (21,527 Ft)</div>
<td>Side 1</td><td>10m</td><td>5m</td>
<li><b>Mixed Use</b>: Retail</li>
General Notes</div><li>Keep setback clear</li><div class="section-header">
<td>1</td><td>100.5</td><td>200.5</td>
"""


class DdaParseTest(unittest.TestCase):
    def test_parse_plot_info_extracts_core_fields(self) -> None:
        row = parse_plot_info(PLOT_INFO_HTML, "P-001")
        self.assertEqual(row["plot_number"], "P-001")
        self.assertEqual(row["old_numbers"], "123, 124")
        self.assertEqual(row["project_name"], "Example Project")
        self.assertEqual(row["community_name"], "Dubai Design District")
        self.assertEqual(row["plot_area_sqm"], "1234")
        self.assertEqual(row["plot_area_sqft"], "13282")
        self.assertEqual(row["max_gfa_sqm"], "2000")
        self.assertEqual(row["side1_building"], "10m")
        self.assertEqual(row["side1_podium"], "5m")
        self.assertIn("Retail", row["land_use"])
        self.assertIn("Keep setback clear", row["general_notes"])
        self.assertIn("100.5", row["coordinates"])

    def test_project_area_row_shapes_geometry(self) -> None:
        row = project_area_row(
            {"attributes": {"OBJECTID": 7, "ProjectName": "Project X"}, "geometry": {"rings": [[[1, 2]]]}}
        )
        self.assertEqual(row["object_id"], 7)
        self.assertEqual(row["project_name"], "Project X")
        self.assertEqual(row["rings"], "[[[1, 2]]]")

    def test_plot_feature_row_maps_type_label(self) -> None:
        row = plot_feature_row(
            {
                "attributes": {
                    "OBJECTID": 5,
                    "PlotNumber": "P-1",
                    "FeatureType": 10,
                    "SHAPE.STArea()": 42,
                    "SHAPE.STLength()": 9,
                },
                "geometry": {"rings": [[[1, 2]]]},
            }
        )
        self.assertEqual(row["feature_type_label"], "Landscape")
        self.assertEqual(row["feature_area_sqm"], 42)
        self.assertEqual(row["feature_perimeter_m"], 9)


if __name__ == "__main__":
    unittest.main()
