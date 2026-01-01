<?php
// Sauvegarde de la partie pour partage
header('Content-Type: text/plain');

// Générer un ID aléatoire pour la partie sauvegardée
$track_id = time() . "_" . rand(1000, 9999);

echo $track_id;
?>
