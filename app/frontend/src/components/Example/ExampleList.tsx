import { Example } from "./Example";

import styles from "./Example.module.css";

export type ExampleModel = {
    text: string;
    value: string;
};

const EXAMPLES: ExampleModel[] = [
    {
        text: "Quel fut le montant du bénéfice net d'Hydro-Québec ? ",
        value: "Quel fut le montant du bénéfice net d'Hydro-Québec ? "
    },
    {
        text: "Quel est le volume des ventes d'électricité à l'exportation ?",
        value: "Quel est le volume des ventes d'électricité à l'exportation ? "
    },
    {
        text: "Quel est le volume des ventes d'électricité à l'exportation ? ",
        value: "Quel est le volume des ventes d'électricité à l'exportation ? "
    }
];

interface Props {
    onExampleClicked: (value: string) => void;
}

export const ExampleList = ({ onExampleClicked }: Props) => {
    return (
        <ul className={styles.examplesNavList}>
            {EXAMPLES.map((x, i) => (
                <li key={i}>
                    <Example text={x.text} value={x.value} onClick={onExampleClicked} />
                </li>
            ))}
        </ul>
    );
};
