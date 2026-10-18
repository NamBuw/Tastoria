package plugins.plantUML.imports.creators;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.vp.plugin.ApplicationManager;
import com.vp.plugin.DiagramManager;
import com.vp.plugin.diagram.IClassDiagramUIModel;
import com.vp.plugin.diagram.IConnectorUIModel;
import com.vp.plugin.diagram.IDiagramElement;
import com.vp.plugin.diagram.IDiagramUIModel;
import com.vp.plugin.diagram.shape.INoteUIModel;
import com.vp.plugin.model.*;
import com.vp.plugin.model.factory.IModelElementFactory;

import plugins.plantUML.models.*;

public abstract class DiagramCreator {
	
	DiagramManager diagramManager = ApplicationManager.instance().getDiagramManager();
	private String diagramTitle;
	Map<IHasChildrenBaseModelElement, SemanticsData> diagramSemanticsMap = new HashMap<IHasChildrenBaseModelElement, SemanticsData>(); // to pass that back to the pipeline to update the master map
	IProject project = ApplicationManager.instance().getProjectManager().getProject();
	IModelElement[] allModelElements = project.toAllLevelModelElementArray();
	Map<String, List<IModelElement>> allModelsMap = new HashMap<>();
	
	protected Map<String, IModelElement> elementMap = new HashMap<>(); // map of entity IDs to modelelements. needed for links
	protected Map<IModelElement, IDiagramElement> shapeMap = new HashMap<>(); // map of modelelements to their created shape UImodels
	
	protected IDiagramUIModel diagram;
	protected List<String> warnings = new ArrayList<>();

	public DiagramCreator(String diagramTitle) {
		this.setDiagramTitle(diagramTitle);	
		
		for (IModelElement projectModelElement : allModelElements) {
			String key = projectModelElement.getName() + "|" + projectModelElement.getModelType();
			allModelsMap.putIfAbsent(key, new ArrayList<>());
		    allModelsMap.get(key).add(projectModelElement);
		}
	}
	
	// Tastoria patch: VP keeps names unique per parent, so root-level elements of every imported diagram
	// (actors, systems, packages, classes, states, notes...) go into one model named after the diagram.
	// Without this, an actor that already exists at root (e.g. from another diagram) silently keeps "ActorNN".
	private IModel diagramNamespace;
	protected void nameIt(IModelElement e, String name) {
		if (e != null && e.getParent() == null) {
			if (diagramNamespace == null) {
				diagramNamespace = IModelElementFactory.instance().createModel();
				diagramNamespace.setName(getDiagramTitle());
			}
			diagramNamespace.addChild(e);
		}
		if (e != null) e.setName(name);
	}

	protected void checkAndSettleNameConflict(String name, String type) {
		if (Boolean.TRUE) return; // Tastoria patch: actors live in separate diagram frames; never rename existing elements
		String key = name + "|" + type; 
		
		List<IModelElement> conflictingElements = allModelsMap.get(key);
		if (conflictingElements == null || conflictingElements.isEmpty()) {
			return;
		}
		for (IModelElement conflictingElement : conflictingElements) {
			LocalDateTime now = LocalDateTime.now();
			DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss");
			String formattedDateTime = now.format(formatter);

			conflictingElement.setName(name + "_renamed_on_import_" + formattedDateTime);
			ApplicationManager.instance().getViewManager().
				showMessage("Warning: the modelElement \""+ name + "\" of type " + type + " was renamed to " + conflictingElement.getName() +
						" due to import of conflicting plantuml element.");
			addWarning("\""+ name + "\" of type " + type + " renamed to " + conflictingElement.getName() +
					" due to import of conflicting plantuml element.");
        }
	}

	protected void createNote(NoteData noteData) {
		INOTE noteModel = IModelElementFactory.instance().createNOTE();
		nameIt(noteModel, noteData.getName());
		noteModel.setDescription(noteData.getContent());
		INoteUIModel noteShape = (INoteUIModel) diagramManager.createDiagramElement(diagram, noteModel);
		elementMap.put(noteData.getUid(), noteModel);
		shapeMap.put(noteModel, noteShape);

		// sequence case::
		if (noteData.getParticipants() != null && !noteData.getParticipants().isEmpty()) {
			for(String participantCode : noteData.getParticipants()) {
				IAnchor anchor = IModelElementFactory.instance().createAnchor();
                IModelElement toElement = elementMap.get(participantCode);
				diagramManager.createConnector(diagram, anchor, shapeMap.get(noteModel),
						shapeMap.get(toElement), null);
			}
		}
	}

	protected void putInSemanticsMap(IHasChildrenBaseModelElement modelElement, BaseWithSemanticsData modelData)  {
		SemanticsData semantics = modelData.getSemantics();
		if (semantics != null)
			diagramSemanticsMap.put(modelElement, modelData.getSemantics());
	}
	
	public String getDiagramTitle() {
		return diagramTitle;
	}

	public void setDiagramTitle(String diagramTitle) {
		this.diagramTitle = diagramTitle;
	}
	public Map<IHasChildrenBaseModelElement, SemanticsData> getDiagramSemanticsMap() {
		return diagramSemanticsMap;
	}

	void createRelationship(RelationshipData relationshipData) {
		String fromID = relationshipData.getSourceID();
		String toID = relationshipData.getTargetID();
		IModelElement fromModelElement = elementMap.get(fromID);
		IModelElement toModelElement = elementMap.get(toID);

		if (fromModelElement == null || toModelElement == null) {
			ApplicationManager.instance().getViewManager()
					.showMessage("Warning: a relationship was skipped because one of its ends was not a previously imported model element.");
			addWarning("A relationship was skipped because one of its ends was not a previously imported model element.");
			return;
		}

		if (relationshipData instanceof AssociationData) {
			createAssociation((AssociationData) relationshipData, fromModelElement, toModelElement);
			return;
		}

		IRelationship relationshipElement;
		switch (relationshipData.getType()) {
			case "Generalization":
				relationshipElement = IModelElementFactory.instance().createGeneralization();
				break;
			case "Realization":
				relationshipElement = IModelElementFactory.instance().createRealization();
				break;
			case "Dependency":
				relationshipElement = IModelElementFactory.instance().createDependency();
				break;
			case "Anchor":
				relationshipElement = IModelElementFactory.instance().createAnchor();
				break;
			case "Containment":
				diagramManager.createConnector(diagram, IClassDiagramUIModel.SHAPETYPE_CONTAINMENT,
						shapeMap.get(fromModelElement), shapeMap.get(toModelElement), null);
				return; // No further configuration for Containment
			case "Transition":
				relationshipElement = IModelElementFactory.instance().createTransition2();
				break;
			default:
				ApplicationManager.instance().getViewManager()
						.showMessage("Warning: unsupported type " + relationshipData.getType() + " of relationship was skipped.");
				addWarning("Unsupported type " + relationshipData.getType() + " of relationship was skipped.");
				return;
		}

		if ("Anchor".equals(relationshipData.getType()) && !(fromModelElement instanceof INOTE) && (toModelElement instanceof INOTE)) {
			IModelElement tmp = fromModelElement; fromModelElement = toModelElement; toModelElement = tmp; // Tastoria patch: VP anchors start at the note
		}
		try {
			relationshipElement.setFrom(fromModelElement);
			relationshipElement.setTo(toModelElement);
		} catch (IllegalArgumentException e) {
			// e.g. PlantUML association class "(A, B) .. C" arrives as an Anchor between two classes
			System.out.println("[tastoria-patch] skipped " + relationshipData.getType() + " " + fromID + " -> " + toID + ": " + e.getMessage());
			addWarning("Skipped " + relationshipData.getType() + " " + fromID + " -> " + toID);
			relationshipElement.delete();
			return;
		}

		if (!"NULL".equals(relationshipData.getName())) {
			relationshipElement.setName(relationshipData.getName());
		}

		IConnectorUIModel connector;
		try {
			connector = (IConnectorUIModel) diagramManager.createConnector(diagram, relationshipElement, shapeMap.get(fromModelElement),
				shapeMap.get(toModelElement), null);
		} catch (IllegalArgumentException e) {
			System.out.println("[tastoria-patch] skipped " + relationshipData.getType() + ": " + e.getMessage());
			addWarning("Skipped " + relationshipData.getType() + ": " + e.getMessage());
			return;
		}
		connector.resetCaption();
	}

	private void createAssociation(AssociationData associationData, IModelElement from, IModelElement to) {
		IAssociation association = IModelElementFactory.instance().createAssociation();
		association.setFrom(from);
		association.setTo(to);
		if ("Aggregation".equals(associationData.getType())) {
			((IAssociationEnd) association.getFromEnd()).setAggregationKind(IAssociationEnd.AGGREGATION_KIND_AGGREGATION);
		} else if ("Composition".equals(associationData.getType())) {
			((IAssociationEnd) association.getFromEnd()).setAggregationKind(IAssociationEnd.AGGREGATION_KIND_COMPOSITED);
		}
		((IAssociationEnd) association.getFromEnd()).setMultiplicity(associationData.getFromEndMultiplicity());
		((IAssociationEnd) association.getToEnd()).setMultiplicity(associationData.getToEndMultiplicity());

		diagramManager.createConnector(diagram, association, shapeMap.get(from), shapeMap.get(to), null);

		if (!"NULL".equals(associationData.getName())) {
			association.setName(associationData.getName());
		}
	}

	protected void addWarning(String warning) {
		warnings.add(warning);
	}

	public void showPopupWarnings() {
		if (warnings.isEmpty()) {
			return;
		}

		String message = String.join("\n", warnings); // Join all warnings with new lines

		System.out.println("[plantuml-vp dialog] " + message);
	}
}
